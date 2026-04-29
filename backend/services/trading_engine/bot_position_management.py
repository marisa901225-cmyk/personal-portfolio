from __future__ import annotations

import logging
from datetime import datetime

from .day_stop_review import (
    review_day_overnight_carry_with_llm,
    review_day_stop_with_llm,
)
from .parking import manage_risk_off_parking
from .position_exit_rules import (
    day_stop_intraday_meta as _day_stop_intraday_meta_helper,
    day_stop_llm_review_key as _day_stop_llm_review_key_helper,
    journal_day_overnight_carry_review as _journal_day_overnight_carry_review_helper,
    journal_day_stop_llm_review as _journal_day_stop_llm_review_helper,
    resolve_day_stop_loss_pct as _resolve_day_stop_loss_pct_helper,
    should_carry_day_force_exit as _should_carry_day_force_exit_helper,
    should_hold_day_stop_after_llm as _should_hold_day_stop_after_llm_helper,
)
from .position_helpers import (
    is_swing_trend_broken,
    lock_profitable_existing_position,
    reconcile_state_with_broker_positions,
)
from .position_monitoring import (
    force_exit_day_positions as _force_exit_day_positions_helper,
    monitor_positions as _monitor_positions_helper,
    record_pending_exit_order as _record_pending_exit_order_helper,
    refresh_pending_exit_orders as _refresh_pending_exit_orders_helper,
)
from .state import PositionState

logger = logging.getLogger(__name__)


class BotPositionManagementMixin:
    def _reconcile_state_with_broker_positions(self, *, now: datetime | None = None) -> None:
        with self._state_lock:
            reconcile_state_with_broker_positions(
                self.api,
                self.state,
                trade_date=self.state.trade_date,
                journal=self._journal,
                notify_text=self._notify_text,
                config=self.config,
                now=now,
                logger=logger,
            )

    def monitor_positions(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now()
        _monitor_positions_helper(self, now=now, logger=logger)

    def force_exit_day_positions(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        _force_exit_day_positions_helper(self, now=now)

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

    def _record_pending_exit_order(self, order: dict, *, strategy_type: str) -> None:
        _record_pending_exit_order_helper(self, order, strategy_type=strategy_type)

    def _refresh_pending_exit_orders(self) -> None:
        _refresh_pending_exit_orders_helper(self, logger=logger)

    def _should_hold_day_stop_after_llm(
        self,
        *,
        code: str,
        pos: PositionState,
        quote_price: float,
        pnl_pct: float,
        reason: str,
        now: datetime,
    ) -> bool:
        return _should_hold_day_stop_after_llm_helper(
            self,
            code=code,
            pos=pos,
            quote_price=quote_price,
            pnl_pct=pnl_pct,
            reason=reason,
            now=now,
            logger=logger,
            review_day_stop_with_llm_fn=review_day_stop_with_llm,
        )

    def _should_carry_day_force_exit(
        self,
        *,
        code: str,
        pos: PositionState,
        quote_price: float,
        reason: str,
    ) -> bool:
        return _should_carry_day_force_exit_helper(
            self,
            code=code,
            pos=pos,
            quote_price=quote_price,
            reason=reason,
            logger=logger,
            review_day_overnight_carry_with_llm_fn=review_day_overnight_carry_with_llm,
        )

    def _day_stop_intraday_meta(self, *, code: str) -> dict[str, object]:
        return _day_stop_intraday_meta_helper(self, code=code, logger=logger)

    def _resolve_day_stop_loss_pct(self, *, code: str) -> float | None:
        return _resolve_day_stop_loss_pct_helper(self, code=code, logger=logger)

    def _journal_day_stop_llm_review(
        self,
        *,
        code: str,
        review,
        intraday_meta: dict[str, object],
    ) -> None:
        _journal_day_stop_llm_review_helper(
            self,
            code=code,
            review=review,
            intraday_meta=intraday_meta,
        )

    def _journal_day_overnight_carry_review(
        self,
        *,
        code: str,
        review,
        intraday_meta: dict[str, object],
    ) -> None:
        _journal_day_overnight_carry_review_helper(
            self,
            code=code,
            review=review,
            intraday_meta=intraday_meta,
        )

    @staticmethod
    def _day_stop_llm_review_key(*, code: str, pos: PositionState) -> str:
        return _day_stop_llm_review_key_helper(code=code, pos=pos)

    def _is_swing_trend_broken(self, *, code: str, quote_price: float, now: datetime) -> bool:
        return is_swing_trend_broken(
            self.api,
            self.config,
            code=code,
            quote_price=quote_price,
            now=now,
            logger=logger,
        )

    def _should_hold_profitable_existing_position(
        self,
        *,
        code: str,
        quotes: dict[str, object],
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
        quotes: dict[str, object],
        candidate_type: str,
        now: datetime,
    ):
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
