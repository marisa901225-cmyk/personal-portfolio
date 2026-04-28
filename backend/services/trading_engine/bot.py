from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from .bot_entry_flow import BotEntryFlowMixin
from .bot_notifications import BotNotificationsMixin
from .bot_position_management import BotPositionManagementMixin
from .config import TradeEngineConfig
from .day_chart_review import review_day_candidates_with_llm, review_swing_candidates_with_llm
from .execution import handle_open_orders
from .interfaces import TradingAPI
from .journal import TradeJournal
from .market_calendar import get_last_trading_day, is_trading_day
from .news_sentiment import build_news_sentiment_signal
from .notifier import BestEffortNotifier
from .notification_text import format_error_message, format_pass_message, format_run_start_message
from .regime import detect_intraday_circuit_breaker, get_regime
from .state import (
    TradeState,
    add_pass_reason,
    get_day_reentry_blocked_codes,
    get_swing_time_excluded_codes,
    load_state,
    rollover_state_for_date,
    save_state,
)
from .strategy import (
    build_candidates,
    exclude_candidate_codes,
    fetch_quotes_subset,
    rank_daytrade_codes,
    rank_swing_codes,
)
from .types import OrderPayload
from .utils import parse_numeric

logger = logging.getLogger(__name__)

_CORE_PASS_REASONS = {"RISK_OFF", "DAILY_MAX_LOSS", "HOLIDAY"}
_ONCE_PER_DAY_PASS_REASONS = {"HOLIDAY", "DAILY_MAX_LOSS", "RISK_OFF"}


class HybridTradingBot(
    BotNotificationsMixin,
    BotPositionManagementMixin,
    BotEntryFlowMixin,
):
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

    def finalize_day(self) -> str | None:
        if not self.journal:
            return None

        today = self.state.trade_date
        realized_pnl = self._finalize_realized_pnl()

        self._journal(
            "RUN_END",
            asof_date=today,
            realized_pnl=realized_pnl,
            pass_reasons=self.state.pass_reasons_today,
            open_positions=len(self.state.open_positions),
        )
        save_state(self.config.state_path, self.state)

        realized_pct = 0.0
        if self.config.initial_capital > 0:
            realized_pct = realized_pnl / self.config.initial_capital * 100.0
        summary_text = (
            f"[마감] {today}\n"
            f"{self.journal.summary()}\n"
            f"실현손익: {realized_pnl:,.0f}원 ({realized_pct:+.2f}%)"
        )
        self._notify_text(summary_text)
        self.notifier.flush(timeout_sec=2.0)
        return summary_text

    def close(self) -> None:
        self.notifier.close(timeout_sec=2.0)

    def _pass(self, reason: str, regime: str) -> None:
        prev_count = int(self.state.pass_reasons_today.get(reason, 0))
        add_pass_reason(self.state, reason)
        self._journal("PASS", asof_date=self.state.trade_date, reason=reason, regime=regime)
        if (not self.config.notify_on_core_pass_only) or reason in _CORE_PASS_REASONS:
            if reason in _ONCE_PER_DAY_PASS_REASONS and prev_count > 0:
                return
            self._notify_text(format_pass_message(reason, self.state.trade_date))

    def _pass_and_return(self, reason: str, now: datetime, regime: str) -> dict[str, object]:
        self._pass(reason, regime)
        self.state.last_run_timestamp = now.isoformat(timespec="seconds")
        save_state(self.config.state_path, self.state)
        return {"status": "PASS", "reason": reason}

    def _ensure_journal(self, today: str) -> None:
        os.makedirs(self.config.output_dir, exist_ok=True)
        if self.journal and self.journal.asof_date == today:
            return
        self.journal = TradeJournal(output_dir=self.config.output_dir, asof_date=today)

    def _journal(self, event: str, **fields: object) -> None:
        if not self.journal:
            return
        self.journal.log(event, **fields)

    @staticmethod
    def _entry_sizing_fields(result: object) -> OrderPayload:
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

    def _finalize_realized_pnl(self) -> float:
        broker_realized_pnl = self._fetch_account_realized_pnl()
        if broker_realized_pnl is not None:
            self.state.realized_pnl_today = broker_realized_pnl
        return float(self.state.realized_pnl_today)

    def _fetch_account_realized_pnl(self) -> float | None:
        inquire_realized_pnl = getattr(self.api, "inquire_realized_pnl", None)
        if not callable(inquire_realized_pnl):
            return None

        try:
            data = inquire_realized_pnl()
        except Exception:
            logger.warning("account realized pnl fetch failed; using state fallback", exc_info=True)
            return None

        if not isinstance(data, dict):
            return None

        total_realized_pnl = self._extract_realized_pnl(data.get("output2"))
        if total_realized_pnl is not None:
            return total_realized_pnl

        output1 = data.get("output1", [])
        if isinstance(output1, list):
            realized_values = [
                value
                for value in (self._extract_realized_pnl(row) for row in output1)
                if value is not None
            ]
            if realized_values:
                return float(sum(realized_values))

        logger.warning("account realized pnl not found in broker response; using state fallback")
        return None

    @staticmethod
    def _extract_realized_pnl(payload: object) -> float | None:
        row = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(row, dict):
            return None
        for key in ("rlzt_pfls", "tot_rlzt_pfls"):
            value = parse_numeric(row.get(key))
            if value is not None:
                return float(value)
        return None

    def has_armed_day_profit_locks(self) -> bool:
        return any(
            pos.type == "T" and pos.qty > 0 and pos.locked_profit_pct is not None
            for pos in self.state.open_positions.values()
        )

    def run_locked_profit_monitor(self, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now()
        today = now.strftime("%Y%m%d")
        self.state = rollover_state_for_date(self.state, today)

        if not self.has_armed_day_profit_locks():
            return {"status": "SKIP", "reason": "NO_ARMED_DAY_LOCKS"}

        self._ensure_journal(today)
        self.monitor_positions(now=now)
        self.state.last_run_timestamp = now.isoformat(timespec="seconds")
        save_state(self.config.state_path, self.state)
        return {
            "status": "OK",
            "reason": "ARMED_DAY_LOCKS_MONITORED",
            "open_positions": len(self.state.open_positions),
        }

    def run_once(self, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now()
        today = now.strftime("%Y%m%d")
        self.state = rollover_state_for_date(self.state, today)
        self._reset_intraday_notification_state(today)
        self._principal_buffer_snapshot = None

        self._ensure_journal(today)

        if not self._run_started:
            self._journal("RUN_START", asof_date=today)
            self._run_started = True
            self._notify_text(format_run_start_message(today))

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
            traded_today_codes = {str(code).strip() for code in self.state.blacklist_today if str(code).strip()}
            eligible_candidates = exclude_candidate_codes(candidates, traded_today_codes)

            handle_open_orders(self.api, timeout_sec=30, now=now)
            self._reconcile_state_with_broker_positions(now=now)
            self._refresh_pending_entry_orders()
            self.monitor_positions(now=now)
            self._manage_risk_off_parking(now=now, regime=regime)

            day_blocked_codes = get_day_reentry_blocked_codes(self.state)
            day_candidates = exclude_candidate_codes(eligible_candidates, day_blocked_codes)
            swing_blocked_codes = get_swing_time_excluded_codes(self.state)
            swing_candidates = exclude_candidate_codes(eligible_candidates, swing_blocked_codes)
            self._journal(
                "SCAN_DONE",
                asof_date=today,
                regime=regime,
                candidates_count=int(len(candidates.merged)),
                blocked_blacklist_codes_count=int(len(traded_today_codes)),
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
            self._maybe_notify_candidates(now, day_candidates, regime, display_candidates=display_candidates)
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
            self._notify_text(format_error_message(today, str(exc)[:180]))
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
