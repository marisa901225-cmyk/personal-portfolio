from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .entry_intraday import (
    apply_day_intraday_confirmation as _apply_day_intraday_confirmation_helper,
    passes_day_intraday_confirmation_for_code as _passes_day_intraday_confirmation_helper,
    resolve_day_lock_retrace_gap_pct as _resolve_day_lock_retrace_gap_pct_helper,
)
from .entry_ordering import (
    build_swing_retry_candidate_frame as _build_swing_retry_candidate_frame_helper,
    krx_tick_size as _krx_tick_size_helper,
    resolve_day_entry_order as _resolve_day_entry_order_helper,
    resolve_swing_candidate_sector as _resolve_swing_candidate_sector_helper,
    resolve_swing_row_sector as _resolve_swing_row_sector_helper,
    swing_retry_codes_with_sector_peers as _swing_retry_codes_with_sector_peers_helper,
)
from .entry_recovery import (
    find_pending_buy_order as _find_pending_buy_order_helper,
    record_pending_entry_order as _record_pending_entry_order_helper,
    recover_failed_buy_attempt as _recover_failed_buy_attempt_helper,
    refresh_pending_entry_orders as _refresh_pending_entry_orders_helper,
    sync_broker_filled_position as _sync_broker_filled_position_helper,
)
from .entry_reviews import (
    apply_day_chart_review as _apply_day_chart_review_helper,
    apply_swing_chart_review as _apply_swing_chart_review_helper,
)
from .execution import FillResult, enter_position
from .notification_text import format_entry_message
from .risk import can_enter, current_entry_window_index
from .types import OrderPayload, Quote, QuoteMap

if TYPE_CHECKING:
    from .news_sentiment import NewsSentimentSignal
    from .strategy import Candidates

logger = logging.getLogger(__name__)


def _bot_module():
    from . import bot as bot_module

    return bot_module


def _krx_tick_size(price: float) -> int:
    return _krx_tick_size_helper(price)


def _resolve_day_entry_order(
    *,
    quote: Quote | None,
    configured_order_type: str,
) -> tuple[str, int | None]:
    return _resolve_day_entry_order_helper(
        quote=quote,
        configured_order_type=configured_order_type,
    )


def _swing_retry_codes_with_sector_peers(
    *,
    ranked_codes: list[str],
    candidates: "Candidates",
    config,
    news_signal: "NewsSentimentSignal | None" = None,
) -> list[str]:
    return _swing_retry_codes_with_sector_peers_helper(
        ranked_codes=ranked_codes,
        candidates=candidates,
        config=config,
        news_signal=news_signal,
    )


def _build_swing_retry_candidate_frame(candidates: "Candidates"):
    return _build_swing_retry_candidate_frame_helper(candidates)


def _resolve_swing_candidate_sector(
    *,
    code: str,
    candidate_frame,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: "NewsSentimentSignal | None" = None,
) -> str:
    return _resolve_swing_candidate_sector_helper(
        code=code,
        candidate_frame=candidate_frame,
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )


def _resolve_swing_row_sector(
    *,
    row,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: "NewsSentimentSignal | None" = None,
) -> str:
    return _resolve_swing_row_sector_helper(
        row=row,
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )


class BotEntryFlowMixin:
    def _try_enter_swing(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Candidates,
        quotes: QuoteMap,
        news_signal: NewsSentimentSignal | None = None,
    ) -> None:
        bot_module = _bot_module()
        ranked_codes = bot_module.rank_swing_codes(candidates, quotes, self.config, news_signal=news_signal)
        code = ranked_codes[0] if ranked_codes else None
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

        ranked_codes, review_applied = self._apply_swing_chart_review(
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
        )
        code = ranked_codes[0] if ranked_codes else None
        if not code:
            self._pass("SWING_LLM_VETO" if review_applied else "NO_SWING_PICK", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="SWING",
                    reason="SWING_LLM_VETO",
                )
            if not review_applied:
                self._maybe_notify_swing_skip(
                    now=now,
                    regime=regime,
                    reason="NO_SWING_PICK",
                    candidates=candidates,
                )
            return

        ranked_codes = _swing_retry_codes_with_sector_peers(
            ranked_codes=ranked_codes,
            candidates=candidates,
            config=self.config,
            news_signal=news_signal,
        )

        result = None
        code = ""
        for ranked_code in ranked_codes:
            attempt = enter_position(
                self.api,
                self.state,
                position_type="S",
                code=ranked_code,
                cash_ratio=self.config.swing_cash_ratio,
                budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.swing_cash_ratio),
                asof_date=self.state.trade_date,
                now=now,
                order_type=self.config.swing_entry_order_type,
                on_order_accepted=lambda order: self._record_pending_entry_order(
                    order,
                    strategy_type="S",
                ),
            )
            if attempt:
                result = attempt
                code = ranked_code
                break
            if ranked_code in self.state.pending_entry_orders:
                return
            synced_result, pending_order = self._recover_failed_buy_attempt(
                code=ranked_code,
                strategy_type="S",
                now=now,
                regime=regime,
            )
            if synced_result is not None:
                result = synced_result
                code = ranked_code
                break
            if pending_order is not None:
                return
        if not result:
            self._pass("SWING_ENTRY_FAILED", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="SWING",
                    reason="SWING_ENTRY_FAILED",
                    code=ranked_codes[0] if ranked_codes else None,
                )
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
        if result.reason == "BROKER_SYNC":
            self._notify_text(
                format_entry_message(
                    strategy="S",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                    sync=True,
                )
            )
        else:
            self._notify_text(
                format_entry_message(
                    strategy="S",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                )
            )

    def _try_enter_day(
        self,
        *,
        now: datetime,
        regime: str,
        candidates: Candidates,
        quotes: QuoteMap,
        news_signal: NewsSentimentSignal | None = None,
    ) -> None:
        bot_module = _bot_module()
        ranked_codes = bot_module.rank_daytrade_codes(candidates, quotes, self.config, news_signal=news_signal)
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

        ranked_codes, review_applied = self._apply_day_chart_review(
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
        )
        if not ranked_codes:
            self._pass("DAY_LLM_VETO" if review_applied else "NO_DAY_PICK", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="DAY",
                    reason="DAY_LLM_VETO",
                )
            return

        self._reconcile_state_with_broker_positions(now=now)
        ok, reason = can_enter(
            "T",
            self.state,
            regime=regime,
            candidates_count=len(ranked_codes),
            now=now,
            config=self.config,
            is_trading_day_value=True,
        )
        if not ok:
            self._pass(reason, regime)
            return

        result = None
        code = ""
        for ranked_code in ranked_codes:
            quote = quotes.get(ranked_code) if isinstance(quotes, dict) else None
            order_type, price = _resolve_day_entry_order(
                quote=quote,
                configured_order_type=self.config.day_entry_order_type,
            )
            attempt = enter_position(
                self.api,
                self.state,
                position_type="T",
                code=ranked_code,
                cash_ratio=self.config.day_cash_ratio,
                budget_cash_cap=self._strategy_budget_cash_cap(cash_ratio=self.config.day_cash_ratio),
                asof_date=self.state.trade_date,
                now=now,
                order_type=order_type,
                price=price,
                on_order_accepted=lambda order: self._record_pending_entry_order(
                    order,
                    strategy_type="T",
                ),
            )
            if attempt:
                result = attempt
                code = ranked_code
                break
            if ranked_code in self.state.pending_entry_orders:
                return
            synced_result, pending_order = self._recover_failed_buy_attempt(
                code=ranked_code,
                strategy_type="T",
                now=now,
                regime=regime,
            )
            if synced_result is not None:
                result = synced_result
                code = ranked_code
                break
            if pending_order is not None:
                return
        if not result:
            self._pass("DAY_ENTRY_FAILED", regime)
            if review_applied:
                self._notify_chart_review_skip(
                    strategy_label="DAY",
                    reason="DAY_ENTRY_FAILED",
                    code=ranked_codes[0] if ranked_codes else None,
                )
            return
        window_index = current_entry_window_index(now, self.config)
        if window_index is not None:
            self.state.day_entry_windows_used_today.add(window_index)

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
        if result.reason == "BROKER_SYNC":
            self._notify_text(
                format_entry_message(
                    strategy="T",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                    sync=True,
                )
            )
        else:
            self._notify_text(
                format_entry_message(
                    strategy="T",
                    code=code,
                    qty=result.qty,
                    avg_price=result.avg_price,
                    regime=regime,
                )
            )

    def _apply_day_intraday_confirmation(
        self,
        ranked_codes: list[str],
        *,
        now: datetime,
    ) -> list[str]:
        del now
        return _apply_day_intraday_confirmation_helper(self, ranked_codes, logger=logger)

    def _passes_day_intraday_confirmation(
        self,
        *,
        code: str,
    ) -> tuple[bool, dict[str, object]]:
        return _passes_day_intraday_confirmation_helper(self, code=code, logger=logger)

    def _resolve_day_lock_retrace_gap_pct(self, *, code: str) -> float | None:
        return _resolve_day_lock_retrace_gap_pct_helper(self, code=code, logger=logger)

    def _apply_day_chart_review(
        self,
        *,
        ranked_codes: list[str],
        candidates: Candidates,
        quotes: QuoteMap,
    ) -> tuple[list[str], bool]:
        bot_module = _bot_module()
        return _apply_day_chart_review_helper(
            self,
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
            review_fn=bot_module.review_day_candidates_with_llm,
        )

    def _apply_swing_chart_review(
        self,
        *,
        ranked_codes: list[str],
        candidates: Candidates,
        quotes: QuoteMap,
    ) -> tuple[list[str], bool]:
        bot_module = _bot_module()
        return _apply_swing_chart_review_helper(
            self,
            ranked_codes=ranked_codes,
            candidates=candidates,
            quotes=quotes,
            review_fn=bot_module.review_swing_candidates_with_llm,
        )

    def _recover_failed_buy_attempt(
        self,
        *,
        code: str,
        strategy_type: str,
        now: datetime,
        regime: str,
    ) -> tuple[FillResult | None, OrderPayload | None]:
        return _recover_failed_buy_attempt_helper(
            self,
            code=code,
            strategy_type=strategy_type,
            now=now,
            regime=regime,
            logger=logger,
        )

    def _record_pending_entry_order(self, order: dict, *, strategy_type: str) -> None:
        _record_pending_entry_order_helper(self, order, strategy_type=strategy_type)

    def _sync_broker_filled_position(
        self,
        *,
        code: str,
        strategy_type: str,
        now: datetime,
        regime: str,
    ) -> FillResult | None:
        return _sync_broker_filled_position_helper(
            self,
            code=code,
            strategy_type=strategy_type,
            now=now,
            regime=regime,
            logger=logger,
        )

    def _find_pending_buy_order(self, *, code: str) -> OrderPayload | None:
        return _find_pending_buy_order_helper(self, code=code, logger=logger)

    def _refresh_pending_entry_orders(self) -> None:
        _refresh_pending_entry_orders_helper(self, logger=logger)
