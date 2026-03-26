from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

from .config import TradeEngineConfig
from .execution import enter_position, exit_position, handle_open_orders
from .interfaces import TradingAPI
from .journal import TradeJournal
from .market_calendar import get_last_trading_day, is_trading_day
from .news_sentiment import build_news_sentiment_signal
from .notifier import BestEffortNotifier
from .regime import detect_intraday_circuit_breaker, get_regime
from .risk import can_enter, should_exit_position
from .state import TradeState, add_pass_reason, load_state, rollover_state_for_date, save_state
from .strategy import build_candidates, fetch_quotes_subset, pick_swing, rank_daytrade_codes
from .utils import compute_sma, parse_hhmm, parse_numeric

logger = logging.getLogger(__name__)

_CORE_PASS_REASONS = {"RISK_OFF", "DAILY_MAX_LOSS", "HOLIDAY"}
_ONCE_PER_DAY_PASS_REASONS = {"HOLIDAY", "DAILY_MAX_LOSS", "RISK_OFF"}


class HybridTradingBot:
    """Hybrid swing/day-trade bot using injected KIS-compatible API interface."""

    def __init__(
        self,
        api: TradingAPI,
        *,
        config: TradeEngineConfig | None = None,
        notifier: BestEffortNotifier | None = None,
    ) -> None:
        self.api = api
        self.config = config or TradeEngineConfig()
        self.state: TradeState = load_state(self.config.state_path)
        self.notifier = notifier or BestEffortNotifier(max_retry=self.config.telegram_retry_max)
        self.journal: TradeJournal | None = None
        self._run_started = False
        self._last_notified_window_idx: int | None = None  # To prevent candidate spam

    def run_once(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now()
        today = now.strftime("%Y%m%d")
        self.state = rollover_state_for_date(self.state, today)

        self._ensure_journal(today)

        if not self._run_started:
            self._journal("RUN_START", asof_date=today)
            self._run_started = True
            self._notify_text(f"[RUN_START] {today}")

        try:
            if not is_trading_day(self.api, today, config=self.config):
                return self._pass_and_return("HOLIDAY", now, regime="N/A")

            # 새 영업일 확인 시에만 bars_held 증가 (중복 증가 방지)
            if self.state.last_bar_date_seen != today:
                from .execution import increment_bars_held
                increment_bars_held(self.state)
                self.state.last_bar_date_seen = today
                logger.info("New trading day confirmed: %s. Incremented bars_held.", today)

            asof = today
            if (now.hour, now.minute) < (9, 0):
                asof = get_last_trading_day(self.api, today, config=self.config)

            regime, detected_panic_date = get_regime(
                self.api,
                asof,
                primary_code=self.config.market_proxy_code,
                confirmation_code=self.config.kosdaq_proxy_code,
                use_confirmation=self.config.use_kosdaq_confirmation,
                last_panic_date=self.state.last_panic_date,
                vol_threshold=self.config.regime_vol_threshold,
            )

            if (
                self.config.use_intraday_circuit_breaker
                and regime != "RISK_OFF"
                and (9, 0) <= (now.hour, now.minute) <= (15, 30)
            ):
                triggered, cb_meta = detect_intraday_circuit_breaker(
                    self.api,
                    asof=today,
                    code=self.config.market_proxy_code,
                    one_bar_drop_pct=self.config.intraday_cb_1bar_drop_pct,
                    window_minutes=self.config.intraday_cb_window_minutes,
                    window_drop_pct=self.config.intraday_cb_window_drop_pct,
                    day_change_pct=self.config.intraday_cb_day_change_pct,
                )
                if triggered:
                    regime = "RISK_OFF"
                    detected_panic_date = today
                    logger.warning(
                        "INTRADAY CB TRIGGERED date=%s code=%s meta=%s",
                        today,
                        self.config.market_proxy_code,
                        cb_meta,
                    )
                    self._journal(
                        "INTRADAY_CB",
                        asof_date=today,
                        code=self.config.market_proxy_code,
                        reason=cb_meta.get("reason"),
                        day_change_pct=cb_meta.get("day_change_pct"),
                        last_bar_drop_pct=cb_meta.get("last_bar_drop_pct"),
                        window_drop_pct=cb_meta.get("window_drop_pct"),
                        window_minutes=cb_meta.get("window_minutes"),
                    )

            if detected_panic_date:
                current_panic_date = self.state.last_panic_date
                if current_panic_date is None or detected_panic_date > current_panic_date:
                    logger.warning(
                        "PANIC DETECTED asof=%s panic_date=%s. Setting last_panic_date.",
                        asof,
                        detected_panic_date,
                    )
                    self.state.last_panic_date = detected_panic_date

            candidates = build_candidates(self.api, asof, self.config)
            self._journal(
                "SCAN_DONE",
                asof_date=today,
                regime=regime,
                candidates_count=int(len(candidates.merged)),
                used_value_proxy=int(candidates.popular["used_value_proxy"].fillna(False).sum())
                if not candidates.popular.empty
                else 0,
            )

            handle_open_orders(self.api, timeout_sec=30)
            self._reconcile_state_with_broker_positions()
            self.monitor_positions(now=now)
            self._manage_risk_off_parking(now=now, regime=regime)

            # --- Candidate Notification ---
            self._maybe_notify_candidates(now, candidates, regime)
            # ------------------------------

            if regime == "RISK_OFF":
                self._pass("RISK_OFF", regime)
                self.state.last_run_timestamp = now.isoformat(timespec="seconds")
                save_state(self.config.state_path, self.state)
                return {"status": "OK", "regime": regime, "asof": asof}

            news_signal = build_news_sentiment_signal(self.config)
            if news_signal is not None:
                self._journal(
                    "NEWS_SENTIMENT",
                    asof_date=today,
                    market_score=round(news_signal.market_score, 4),
                    article_count=int(news_signal.article_count),
                )

            quotes = fetch_quotes_subset(self.api, candidates.quote_codes)
            self._try_enter_swing(
                now=now,
                regime=regime,
                candidates=candidates,
                quotes=quotes,
                news_signal=news_signal,
            )
            self._try_enter_day(
                now=now,
                regime=regime,
                candidates=candidates,
                quotes=quotes,
                news_signal=news_signal,
            )

            self.force_exit_day_positions(now)
            self.state.last_run_timestamp = now.isoformat(timespec="seconds")
            save_state(self.config.state_path, self.state)
            return {"status": "OK", "regime": regime, "asof": asof}
        except Exception as exc:
            logger.exception("bot run failed: %s", exc)
            self._journal("ERROR", asof_date=today, reason=str(exc))
            self._notify_text(f"[ERROR] {today} {str(exc)[:180]}")
            save_state(self.config.state_path, self.state)
            return {"status": "ERROR", "error": str(exc)}

    def run_until_close(self, *, sleep_sec: int | None = None) -> None:
        interval = sleep_sec or self.config.monitor_interval_sec
        while True:
            now = datetime.now()
            self.run_once(now=now)
            if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
                break
            time.sleep(max(30, int(interval)))

    def finalize_day(self) -> str | None:
        if not self.journal:
            return None

        today = self.state.trade_date

        self._journal(
            "RUN_END",
            asof_date=today,
            realized_pnl=self.state.realized_pnl_today,
            pass_reasons=self.state.pass_reasons_today,
            open_positions=len(self.state.open_positions),
        )
        save_state(self.config.state_path, self.state)

        zip_path = self.journal.make_backup_zip(
            state_file=self.config.state_path,
            runlog_file=self.config.runlog_path,
        )
        self.notifier.enqueue_file(zip_path, caption=f"trade backup {today}")

        realized_pct = 0.0
        if self.config.initial_capital > 0:
            realized_pct = self.state.realized_pnl_today / self.config.initial_capital * 100.0
        self._notify_text(
            f"[마감] {today}\n"
            f"{self.journal.summary()}\n"
            f"실현손익: {self.state.realized_pnl_today:,.0f}원 ({realized_pct:+.2f}%)"
        )
        self.notifier.flush(timeout_sec=2.0)
        return zip_path

    def close(self) -> None:
        self.notifier.close(timeout_sec=2.0)

    def _reconcile_state_with_broker_positions(self) -> None:
        try:
            broker_positions = self.api.positions() or []
        except Exception as exc:
            logger.warning("positions reconcile skipped: failed to load broker positions: %s", exc)
            return

        broker_codes: set[str] = set()
        for item in broker_positions:
            code = str(item.get("code") or item.get("pdno") or "").strip()
            qty = int(parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0)
            if code and qty > 0:
                broker_codes.add(code)

        stale_codes = [
            code
            for code in self.state.open_positions
            if code not in broker_codes
        ]
        for code in stale_codes:
            pos = self.state.open_positions.pop(code, None)
            if not pos:
                continue
            logger.warning(
                "state reconcile dropped stale position code=%s type=%s qty=%s",
                code,
                pos.type,
                pos.qty,
            )
            self._journal(
                "STATE_RECONCILE_DROP",
                asof_date=self.state.trade_date,
                code=code,
                qty=pos.qty,
                reason="BROKER_POSITION_MISSING",
                strategy_type=pos.type,
            )
            self._notify_text(
                f"[STATE_SYNC][DROP] {code} local_qty={pos.qty} broker_qty=0"
            )

    def monitor_positions(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now()
        for code, pos in list(self.state.open_positions.items()):
            try:
                q = self.api.quote(code)
            except Exception:
                continue
            price = parse_numeric(q.get("price"))
            if price is None:
                continue

            swing_trend_broken: bool | None = None
            if pos.type == "S" and self.config.swing_sl_requires_trend_break:
                swing_trend_broken = self._is_swing_trend_broken(code=code, quote_price=price, now=now)

            exit_now, reason, pnl_pct = should_exit_position(
                pos,
                quote_price=price,
                now=now,
                config=self.config,
                swing_trend_broken=swing_trend_broken,
            )
            if not exit_now:
                continue

            result = exit_position(self.api, self.state, code=code, reason=reason, now=now)
            if not result:
                continue

            self._journal(
                "EXIT_FILL",
                asof_date=self.state.trade_date,
                code=code,
                side="SELL",
                qty=result.qty,
                avg_price=result.avg_price,
                pnl_pct=round(pnl_pct * 100.0, 4),
                reason=reason,
                strategy_type=pos.type,
            )
            self._notify_text(
                f"[EXIT][{pos.type}][{reason}] {code} qty={result.qty} avg={result.avg_price:.0f} pnl={pnl_pct * 100:+.2f}%"
            )

    def force_exit_day_positions(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        force_h, force_m = map(int, self.config.day_force_exit_at.split(":"))
        if (now.hour, now.minute) < (force_h, force_m):
            return

        for code, pos in list(self.state.open_positions.items()):
            if pos.type != "T":
                continue
            result = exit_position(self.api, self.state, code=code, reason="FORCE", now=now)
            if not result:
                continue
            self._journal(
                "FORCE_EXIT",
                asof_date=self.state.trade_date,
                code=code,
                side="SELL",
                qty=result.qty,
                avg_price=result.avg_price,
                reason="FORCE",
                strategy_type="T",
            )

    def _manage_risk_off_parking(self, *, now: datetime, regime: str) -> None:
        parking_codes = self._parking_position_codes()
        parking_code = str(self.config.risk_off_parking_code).strip()
        parking_enabled = bool(self.config.risk_off_parking_enabled and parking_code)
        existing_parking = self.state.open_positions.get(parking_code)

        if regime != "RISK_OFF" or not parking_enabled:
            if not parking_codes or not self._is_regular_market_open(now):
                return
            reason = "RISK_ON" if regime != "RISK_OFF" else "PARKING_DISABLED"
            self._exit_risk_off_parking_positions(now=now, reason=reason)
            return

        if parking_codes and parking_code not in parking_codes and self._is_regular_market_open(now):
            self._exit_risk_off_parking_positions(now=now, reason="PARKING_ROTATE")
            parking_codes = self._parking_position_codes()
            if parking_codes:
                return

        if not self._can_enter_risk_off_parking(now):
            return
        if existing_parking is None and len(self.state.open_positions) >= self.config.max_total_positions:
            return

        result = enter_position(
            self.api,
            self.state,
            position_type="P",
            code=parking_code,
            cash_ratio=self.config.risk_off_parking_cash_ratio,
            asof_date=self.state.trade_date,
            now=now,
            order_type=self.config.risk_off_parking_order_type,
        )
        if not result:
            return

        self._journal(
            "ENTRY_FILL",
            asof_date=self.state.trade_date,
            code=parking_code,
            side="BUY",
            qty=result.qty,
            avg_price=result.avg_price,
            strategy_type="P",
            regime=regime,
        )
        self._notify_text(
            f"[ENTRY][P][RISK_OFF] {parking_code} qty={result.qty} avg={result.avg_price:.0f}"
        )

    def _exit_risk_off_parking_positions(self, *, now: datetime, reason: str) -> None:
        for code in list(self._parking_position_codes()):
            pos = self.state.open_positions.get(code)
            if not pos:
                continue

            entry_price = float(pos.entry_price or 0.0)
            result = exit_position(self.api, self.state, code=code, reason=reason, now=now)
            if not result:
                continue

            pnl_pct = 0.0
            if entry_price > 0:
                pnl_pct = (result.avg_price / entry_price - 1.0) * 100.0

            self._journal(
                "EXIT_FILL",
                asof_date=self.state.trade_date,
                code=code,
                side="SELL",
                qty=result.qty,
                avg_price=result.avg_price,
                pnl_pct=round(pnl_pct, 4),
                reason=reason,
                strategy_type="P",
            )
            self._notify_text(
                f"[EXIT][P][{reason}] {code} qty={result.qty} avg={result.avg_price:.0f} pnl={pnl_pct:+.2f}%"
            )

    def _parking_position_codes(self) -> list[str]:
        return [
            code
            for code, pos in self.state.open_positions.items()
            if pos.type == "P"
        ]

    def _is_regular_market_open(self, now: datetime) -> bool:
        return (9, 0) <= (now.hour, now.minute) <= (15, 30)

    def _can_enter_risk_off_parking(self, now: datetime) -> bool:
        if not self._is_regular_market_open(now):
            return False
        close_h, close_m = parse_hhmm(self.config.no_new_entry_after)
        return (now.hour, now.minute) < (close_h, close_m)

    def _try_enter_swing(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Any,
        quotes: dict[str, Any],
        news_signal: Any | None = None,
    ) -> None:
        candidate_count = len(candidates.model) + len(candidates.etf)
        ok, reason = can_enter(
            "S",
            self.state,
            regime=regime,
            candidates_count=candidate_count,
            now=now,
            config=self.config,
            is_trading_day_value=True,
        )
        if not ok:
            self._pass(reason, regime)
            return

        code = pick_swing(candidates, quotes, self.config, news_signal=news_signal)
        if not code:
            self._pass("NO_SWING_PICK", regime)
            return

        result = enter_position(
            self.api,
            self.state,
            position_type="S",
            code=code,
            cash_ratio=self.config.swing_cash_ratio,
            asof_date=self.state.trade_date,
            now=now,
            order_type=self.config.swing_entry_order_type,
        )
        if not result:
            self._pass("SWING_ENTRY_FAILED", regime)
            return

        self._journal(
            "ENTRY_FILL",
            asof_date=self.state.trade_date,
            code=code,
            side="BUY",
            qty=result.qty,
            avg_price=result.avg_price,
            strategy_type="S",
            regime=regime,
        )
        self._notify_text(f"[ENTRY][S] {code} qty={result.qty} avg={result.avg_price:.0f} regime={regime}")

    def _try_enter_day(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Any,
        quotes: dict[str, Any],
        news_signal: Any | None = None,
    ) -> None:
        ok, reason = can_enter(
            "T",
            self.state,
            regime=regime,
            candidates_count=len(candidates.popular),
            now=now,
            config=self.config,
            is_trading_day_value=True,
        )
        if not ok:
            self._pass(reason, regime)
            return

        ranked_codes = rank_daytrade_codes(candidates, quotes, self.config, news_signal=news_signal)
        if not ranked_codes:
            self._pass("NO_DAY_PICK", regime)
            return

        result = None
        code = ""
        for ranked_code in ranked_codes:
            attempt = enter_position(
                self.api,
                self.state,
                position_type="T",
                code=ranked_code,
                cash_ratio=self.config.day_cash_ratio,
                asof_date=self.state.trade_date,
                now=now,
                order_type=self.config.day_entry_order_type,
            )
            if attempt:
                result = attempt
                code = ranked_code
                break
        if not result:
            self._pass("DAY_ENTRY_FAILED", regime)
            return

        self._journal(
            "ENTRY_FILL",
            asof_date=self.state.trade_date,
            code=code,
            side="BUY",
            qty=result.qty,
            avg_price=result.avg_price,
            strategy_type="T",
            regime=regime,
        )
        self._notify_text(f"[ENTRY][T] {code} qty={result.qty} avg={result.avg_price:.0f} regime={regime}")

    def _pass(self, reason: str, regime: str) -> None:
        prev_count = int(self.state.pass_reasons_today.get(reason, 0))
        add_pass_reason(self.state, reason)
        self._journal("PASS", asof_date=self.state.trade_date, reason=reason, regime=regime)
        if (not self.config.notify_on_core_pass_only) or reason in _CORE_PASS_REASONS:
            if reason in _ONCE_PER_DAY_PASS_REASONS and prev_count > 0:
                return
            self._notify_text(f"[PASS] {reason} {self.state.trade_date}")

    def _pass_and_return(self, reason: str, now: datetime, regime: str) -> dict[str, Any]:
        self._pass(reason, regime)
        self.state.last_run_timestamp = now.isoformat(timespec="seconds")
        save_state(self.config.state_path, self.state)
        return {"status": "PASS", "reason": reason}

    def _is_swing_trend_broken(self, *, code: str, quote_price: float, now: datetime) -> bool:
        ma_window = max(2, int(self.config.swing_trend_ma_window))
        lookback = max(ma_window + 5, int(self.config.swing_trend_lookback_bars))
        asof = now.strftime("%Y%m%d")
        try:
            bars = self.api.daily_bars(code, asof, lookback)
        except Exception:
            logger.debug("trend check daily_bars failed code=%s", code, exc_info=True)
            return False

        if bars is None or bars.empty or "close" not in bars.columns:
            return False

        close_s = bars["close"]
        if len(close_s) < ma_window:
            return False

        ma_s = compute_sma(close_s, ma_window)
        ma_value = parse_numeric(ma_s.iloc[-1]) if len(ma_s) else None
        if ma_value is None or ma_value <= 0:
            return False

        buffer_pct = max(0.0, float(self.config.swing_trend_break_buffer_pct))
        threshold = ma_value * (1.0 - buffer_pct)
        return quote_price < threshold

    def _ensure_journal(self, today: str) -> None:
        os.makedirs(self.config.output_dir, exist_ok=True)
        if self.journal and self.journal.asof_date == today:
            return
        self.journal = TradeJournal(output_dir=self.config.output_dir, asof_date=today)

    def _journal(self, event: str, **fields: Any) -> None:
        if not self.journal:
            return
        self.journal.log(event, **fields)

    def _notify_text(self, msg: str) -> None:
        self.notifier.enqueue_text(msg)

    def _maybe_notify_candidates(self, now: datetime, candidates: Any, regime: str) -> None:
        """진입 시간대에 후보 종목 리스트를 텔레그램으로 쏩니다 (윈도우당 1회)"""
        if candidates.merged.empty:
            return

        # 현재 어느 윈도우에 있는지 확인
        current_window_idx: int | None = None
        from .risk import _is_in_window
        for i, (start, end) in enumerate(self.config.entry_windows):
            if _is_in_window(now, start, end):
                current_window_idx = i
                break

        if current_window_idx is None:
            # 진입 시간대가 아니면 무시 (또는 필요시 정책에 따라 변경)
            return

        # 이미 이 윈도우에서 보냈으면 생략
        if self._last_notified_window_idx == current_window_idx:
            return

        self._last_notified_window_idx = current_window_idx

        # 상위 10개 포맷팅
        top_10 = candidates.merged.head(10)
        lines = [f"🎯 [Entry Window] Scanned Symbols ({regime})"]
        if regime == "RISK_OFF":
            lines.append("※ RISK_OFF 상태: 후보 관찰 전용 (공격적 신규 진입 차단)")
            if self.config.risk_off_parking_enabled and self.config.risk_off_parking_code:
                lines.append(f"※ 여유 현금 파킹 대상: {self.config.risk_off_parking_code}")
        for i, (_, row) in enumerate(top_10.iterrows(), 1):
            code = row["code"]
            name = row["name"]
            val5 = parse_numeric(row.get("avg_value_5d")) or 0
            val20 = parse_numeric(row.get("avg_value_20d")) or 0
            val = max(val5, val20)
            lines.append(f"{i}. {name}({code}) | {val/1e8:.1f}억")

        self._notify_text("\n".join(lines))
