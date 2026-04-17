from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any

import pandas as pd

from .candidate_notifications import (
    maybe_build_candidate_notifications,
    maybe_build_swing_skip_notification,
)
from .config import TradeEngineConfig
from .execution import enter_position, exit_position, handle_open_orders
from .intraday import passes_day_intraday_confirmation
from .interfaces import TradingAPI
from .journal import TradeJournal
from .market_calendar import get_last_trading_day, is_trading_day
from .news_sentiment import build_news_sentiment_signal
from .notifier import BestEffortNotifier
from .parking import manage_risk_off_parking
from .position_helpers import (
    is_swing_trend_broken,
    lock_profitable_existing_position,
    reconcile_state_with_broker_positions,
)
from .regime import detect_intraday_circuit_breaker, get_regime
from .risk import can_enter, should_exit_position
from .state import (
    PositionState,
    TradeState,
    add_pass_reason,
    get_day_stoploss_excluded_codes,
    get_swing_time_excluded_codes,
    load_state,
    rollover_state_for_date,
    save_state,
)
from .strategy import (
    build_candidates,
    exclude_candidate_codes,
    fetch_quotes_subset,
    pick_swing,
    rank_daytrade_codes,
)
from .utils import parse_numeric

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
        self._last_swing_skip_notified_window_idx: int | None = None
        self._last_notification_trade_date: str | None = None
        self._principal_buffer_snapshot: float | None = None

    def run_once(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now()
        today = now.strftime("%Y%m%d")
        self.state = rollover_state_for_date(self.state, today)
        self._reset_intraday_notification_state(today)
        self._principal_buffer_snapshot = None

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

            news_signal = build_news_sentiment_signal(self.config)
            candidates = build_candidates(self.api, asof, self.config, news_signal=news_signal)

            handle_open_orders(self.api, timeout_sec=30, now=now)
            self._reconcile_state_with_broker_positions()
            self.monitor_positions(now=now)
            self._manage_risk_off_parking(now=now, regime=regime)

            day_blocked_codes = get_day_stoploss_excluded_codes(self.state)
            day_candidates = exclude_candidate_codes(candidates, day_blocked_codes)
            swing_blocked_codes = get_swing_time_excluded_codes(self.state)
            swing_candidates = exclude_candidate_codes(candidates, swing_blocked_codes)
            self._journal(
                "SCAN_DONE",
                asof_date=today,
                regime=regime,
                candidates_count=int(len(candidates.merged)),
                blocked_day_stoploss_codes_count=int(len(day_blocked_codes)),
                blocked_swing_time_codes_count=int(len(swing_blocked_codes)),
                used_value_proxy=int(candidates.popular["used_value_proxy"].fillna(False).sum())
                if (not candidates.popular.empty and "used_value_proxy" in candidates.popular.columns)
                else 0,
            )

            if news_signal is not None:
                self._journal(
                    "NEWS_SENTIMENT",
                    asof_date=today,
                    market_score=round(news_signal.market_score, 4),
                    article_count=int(news_signal.article_count),
                )

            quotes = fetch_quotes_subset(self.api, candidates.quote_codes)
            ranked_day_codes = rank_daytrade_codes(day_candidates, quotes, self.config, news_signal=news_signal)
            ranked_day_codes = self._apply_day_intraday_confirmation(ranked_day_codes, now=now)
            display_candidates = self._build_notification_candidates(
                candidates=day_candidates,
                ranked_codes=ranked_day_codes,
            )

            # --- Candidate Notification ---
            self._maybe_notify_candidates(now, candidates, regime, display_candidates=display_candidates)
            # ------------------------------

            if regime == "RISK_OFF":
                self._pass("RISK_OFF", regime)
                self.state.last_run_timestamp = now.isoformat(timespec="seconds")
                save_state(self.config.state_path, self.state)
                return {"status": "OK", "regime": regime, "asof": asof}

            self._try_enter_swing(
                now=now,
                regime=regime,
                candidates=swing_candidates,
                quotes=quotes,
                news_signal=news_signal,
            )
            self._try_enter_day(
                now=now,
                regime=regime,
                candidates=day_candidates,
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

        realized_pct = 0.0
        if self.config.initial_capital > 0:
            realized_pct = self.state.realized_pnl_today / self.config.initial_capital * 100.0
        summary_text = (
            f"[마감] {today}\n"
            f"{self.journal.summary()}\n"
            f"실현손익: {self.state.realized_pnl_today:,.0f}원 ({realized_pct:+.2f}%)"
        )
        self._notify_text(summary_text)
        self.notifier.flush(timeout_sec=2.0)
        return summary_text

    def close(self) -> None:
        self.notifier.close(timeout_sec=2.0)

    def _reconcile_state_with_broker_positions(self) -> None:
        reconcile_state_with_broker_positions(
            self.api,
            self.state,
            trade_date=self.state.trade_date,
            journal=self._journal,
            notify_text=self._notify_text,
            logger=logger,
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
            day_lock_retrace_gap_pct_override: float | None = None
            if pos.type == "S" and self.config.swing_sl_requires_trend_break:
                swing_trend_broken = self._is_swing_trend_broken(code=code, quote_price=price, now=now)
            elif pos.type == "T":
                day_lock_retrace_gap_pct_override = self._resolve_day_lock_retrace_gap_pct(code=code)

            exit_now, reason, pnl_pct = should_exit_position(
                pos,
                quote_price=price,
                now=now,
                config=self.config,
                swing_trend_broken=swing_trend_broken,
                day_lock_retrace_gap_pct_override=day_lock_retrace_gap_pct_override,
            )
            if not exit_now:
                continue

            result = exit_position(
                self.api,
                self.state,
                code=code,
                reason=reason,
                now=now,
                config=self.config,
            )
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
            result = exit_position(
                self.api,
                self.state,
                code=code,
                reason="FORCE",
                now=now,
                config=self.config,
            )
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
        manage_risk_off_parking(
            self.api,
            self.state,
            self.config,
            trade_date=self.state.trade_date,
            now=now,
            regime=regime,
            journal=self._journal,
            notify_text=self._notify_text,
        )

    def _try_enter_swing(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Any,
        quotes: dict[str, Any],
        news_signal: Any | None = None,
    ) -> None:
        code = pick_swing(candidates, quotes, self.config, news_signal=news_signal)
        if code and self._should_hold_profitable_existing_position(
            code=code,
            quotes=quotes,
            candidate_type="S",
            now=now,
        ):
            return

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
            if reason == "NO_CANDIDATE":
                self._maybe_notify_swing_skip(now=now, regime=regime, reason=reason, candidates=candidates)
            return

        if not code:
            self._pass("NO_SWING_PICK", regime)
            self._maybe_notify_swing_skip(
                now=now,
                regime=regime,
                reason="NO_SWING_PICK",
                candidates=candidates,
            )
            return

        result = enter_position(
            self.api,
            self.state,
            position_type="S",
            code=code,
            cash_ratio=self.config.swing_cash_ratio,
            budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.swing_cash_ratio),
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
            **self._entry_sizing_fields(result),
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
        ranked_codes = rank_daytrade_codes(candidates, quotes, self.config, news_signal=news_signal)
        ranked_codes = self._apply_day_intraday_confirmation(ranked_codes, now=now)
        if ranked_codes and self._should_hold_profitable_existing_position(
            code=ranked_codes[0],
            quotes=quotes,
            candidate_type="T",
            now=now,
        ):
            return

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
                budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.day_cash_ratio),
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
            **self._entry_sizing_fields(result),
        )
        self._notify_text(f"[ENTRY][T] {code} qty={result.qty} avg={result.avg_price:.0f} regime={regime}")

    def _apply_day_intraday_confirmation(
        self,
        ranked_codes: list[str],
        *,
        now: datetime,
    ) -> list[str]:
        del now
        if not ranked_codes or not self.config.day_use_intraday_confirmation:
            return ranked_codes

        filtered_codes: list[str] = []
        for code in ranked_codes:
            ok, meta = self._passes_day_intraday_confirmation(code=code)
            if ok:
                filtered_codes.append(code)
                continue

            self._journal(
                "DAY_CANDIDATE_FILTERED",
                asof_date=self.state.trade_date,
                code=code,
                reason=meta.get("reason"),
                bars=meta.get("bars"),
                window_change_pct=meta.get("window_change_pct"),
                last_bar_change_pct=meta.get("last_bar_change_pct"),
                retrace_from_high_pct=meta.get("retrace_from_high_pct"),
                recent_range_pct=meta.get("recent_range_pct"),
                day_change_pct=meta.get("day_change_pct"),
            )

        return filtered_codes

    def _passes_day_intraday_confirmation(
        self,
        *,
        code: str,
    ) -> tuple[bool, dict[str, Any]]:
        return passes_day_intraday_confirmation(
            self.api,
            trade_date=self.state.trade_date,
            code=code,
            config=self.config,
            logger=logger,
        )

    def _resolve_day_lock_retrace_gap_pct(self, *, code: str) -> float | None:
        multiplier = max(0.0, float(getattr(self.config, "day_lock_volatility_gap_multiplier", 0.0)))
        if multiplier <= 0:
            return None

        _, meta = self._passes_day_intraday_confirmation(code=code)
        recent_range_pct = parse_numeric(meta.get("recent_range_pct"))
        if recent_range_pct is None or recent_range_pct <= 0:
            return None

        adaptive_gap_pct = (float(recent_range_pct) / 100.0) * multiplier
        return max(float(self.config.day_lock_retrace_gap_pct), adaptive_gap_pct)

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
        return is_swing_trend_broken(
            self.api,
            self.config,
            code=code,
            quote_price=quote_price,
            now=now,
            logger=logger,
        )

    def _ensure_journal(self, today: str) -> None:
        os.makedirs(self.config.output_dir, exist_ok=True)
        if self.journal and self.journal.asof_date == today:
            return
        self.journal = TradeJournal(output_dir=self.config.output_dir, asof_date=today)

    def _journal(self, event: str, **fields: Any) -> None:
        if not self.journal:
            return
        self.journal.log(event, **fields)

    @staticmethod
    def _entry_sizing_fields(result: Any) -> dict[str, Any]:
        sizing = getattr(result, "sizing", None) or {}
        if not isinstance(sizing, dict):
            return {}
        return dict(sizing)

    def _strategy_budget_cash_cap(self, *, cash_ratio: float) -> float | None:
        base_cap = max(0.0, float(self.config.initial_capital) * float(cash_ratio))
        if not self.config.use_realized_profit_buffer:
            return base_cap

        profit_buffer = self._principal_buffer_from_account()
        return max(0.0, base_cap + profit_buffer)

    def _principal_buffer_from_account(self) -> float:
        if self._principal_buffer_snapshot is not None:
            return self._principal_buffer_snapshot

        fallback_buffer = max(0.0, float(getattr(self.state, "realized_pnl_total", 0.0)))
        try:
            cash_available = max(0.0, float(self.api.cash_available()))
            positions = self.api.positions() or []
            cost_basis_total = 0.0
            for item in positions:
                qty = parse_numeric(item.get("qty") or item.get("hldg_qty"))
                avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
                if qty is None or avg_price is None or qty <= 0 or avg_price <= 0:
                    continue
                cost_basis_total += float(qty) * float(avg_price)

            account_basis_total = cash_available + cost_basis_total
            principal_buffer = max(0.0, account_basis_total - float(self.config.initial_capital))
            self._principal_buffer_snapshot = max(principal_buffer, fallback_buffer)
        except Exception:
            logger.warning("principal buffer account snapshot failed; using state fallback", exc_info=True)
            self._principal_buffer_snapshot = fallback_buffer

        return self._principal_buffer_snapshot

    def _should_hold_profitable_existing_position(
        self,
        *,
        code: str,
        quotes: dict[str, Any],
        candidate_type: str,
        now: datetime,
    ) -> bool:
        pnl_ratio, position = self._lock_profitable_existing_position(
            code=code,
            quotes=quotes,
            candidate_type=candidate_type,
            now=now,
        )
        if pnl_ratio is None:
            return False

        self._journal(
            "HOLD_MATCH",
            asof_date=self.state.trade_date,
            code=code,
            reason="ALREADY_HELD_PROFITABLE",
            candidate_strategy_type=candidate_type,
            existing_strategy_type=position.type,
            pnl_pct=round(pnl_ratio * 100.0, 4),
            locked_profit_pct=round(float(position.locked_profit_pct or 0.0) * 100.0, 4),
        )
        logger.info(
            "hold profitable existing position code=%s candidate_type=%s existing_type=%s pnl_pct=%.4f locked_profit_pct=%.4f",
            code,
            candidate_type,
            position.type,
            pnl_ratio * 100.0,
            float(position.locked_profit_pct or 0.0) * 100.0,
        )
        return True

    def _lock_profitable_existing_position(
        self,
        *,
        code: str,
        quotes: dict[str, Any],
        candidate_type: str,
        now: datetime,
    ) -> tuple[float | None, PositionState | None]:
        return lock_profitable_existing_position(
            self.api,
            self.state,
            trade_date=self.state.trade_date,
            code=code,
            quotes=quotes,
            candidate_type=candidate_type,
            now=now,
            logger=logger,
        )


    def _notify_text(self, msg: str) -> None:
        self.notifier.enqueue_text(msg)

    def _maybe_notify_candidates(
        self,
        now: datetime,
        candidates: Any,
        regime: str,
        display_candidates: Any | None = None,
    ) -> None:
        updated_idx, messages = maybe_build_candidate_notifications(
            now=now,
            candidates=candidates,
            regime=regime,
            config=self.config,
            last_notified_window_idx=self._last_notified_window_idx,
            display_candidates=display_candidates,
        )
        self._last_notified_window_idx = updated_idx
        for message in messages:
            self._notify_text(message)

    def _build_notification_candidates(self, *, candidates: Any, ranked_codes: list[str]) -> pd.DataFrame:
        if not ranked_codes or candidates is None:
            return pd.DataFrame()

        popular = getattr(candidates, "popular", None)
        if popular is None or getattr(popular, "empty", True):
            return pd.DataFrame()

        pool = popular.copy()
        if "code" not in pool.columns:
            return pd.DataFrame()

        ordered_frames: list[pd.DataFrame] = []
        seen: set[str] = set()
        for code in ranked_codes:
            code_str = str(code)
            if not code_str or code_str in seen:
                continue
            rows = pool[pool["code"].astype(str) == code_str]
            if rows.empty:
                continue
            ordered_frames.append(rows.head(1))
            seen.add(code_str)

        if not ordered_frames:
            return pd.DataFrame()
        return pd.concat(ordered_frames, ignore_index=True)

    def _maybe_notify_swing_skip(
        self,
        *,
        now: datetime,
        regime: str,
        reason: str,
        candidates: Any,
    ) -> None:
        if any(position.type == "S" for position in self.state.open_positions.values()):
            return

        updated_idx, message = maybe_build_swing_skip_notification(
            now=now,
            trade_date=self.state.trade_date,
            regime=regime,
            config=self.config,
            last_notified_window_idx=self._last_swing_skip_notified_window_idx,
            reason=reason,
            model_count=len(candidates.model),
            etf_count=len(candidates.etf),
        )
        self._last_swing_skip_notified_window_idx = updated_idx
        if message:
            self._notify_text(message)

    def _reset_intraday_notification_state(self, trade_date: str) -> None:
        if self._last_notification_trade_date == trade_date:
            return
        self._last_notification_trade_date = trade_date
        self._last_notified_window_idx = None
        self._last_swing_skip_notified_window_idx = None
