from __future__ import annotations

import logging
from datetime import datetime

from .day_stop_review import (
    DayOvernightCarryReviewResult,
    DayStopReviewResult,
    is_day_overnight_carry_candidate,
    is_day_stop_review_candidate,
    review_day_overnight_carry_with_llm,
    review_day_stop_with_llm,
)
from .execution import exit_position
from .intraday import passes_day_intraday_confirmation
from .notification_text import format_exit_message
from .parking import manage_risk_off_parking
from .position_helpers import (
    is_swing_trend_broken,
    lock_profitable_existing_position,
    reconcile_state_with_broker_positions,
)
from .risk import should_exit_position
from .state import PositionState
from .utils import parse_numeric

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
        with self._state_lock:
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
                day_stop_loss_pct_override: float | None = None
                if pos.type == "S" and self.config.swing_sl_requires_trend_break:
                    swing_trend_broken = self._is_swing_trend_broken(code=code, quote_price=price, now=now)
                elif pos.type == "T":
                    day_lock_retrace_gap_pct_override = self._resolve_day_lock_retrace_gap_pct(code=code)
                    day_stop_loss_pct_override = self._resolve_day_stop_loss_pct(code=code)

                exit_now, reason, pnl_pct = should_exit_position(
                    pos,
                    quote_price=price,
                    now=now,
                    config=self.config,
                    swing_trend_broken=swing_trend_broken,
                    day_lock_retrace_gap_pct_override=day_lock_retrace_gap_pct_override,
                    day_stop_loss_pct_override=day_stop_loss_pct_override,
                )
                if not exit_now:
                    continue
                if self._should_hold_day_stop_after_llm(
                    code=code,
                    pos=pos,
                    quote_price=price,
                    pnl_pct=pnl_pct,
                    reason=reason,
                    now=now,
                ):
                    continue
                if self._should_carry_day_force_exit(
                    code=code,
                    pos=pos,
                    quote_price=price,
                    reason=reason,
                ):
                    continue

                result = exit_position(
                    self.api,
                    self.state,
                    code=code,
                    reason=reason,
                    now=now,
                    config=self.config,
                    on_order_accepted=lambda order, pos=pos: self._record_pending_exit_order(
                        order,
                        strategy_type=pos.type,
                    ),
                )
                if not result:
                    continue

                self.state.pending_exit_orders.pop(code, None)
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
                    format_exit_message(
                        strategy=pos.type,
                        reason=reason,
                        code=code,
                        qty=result.qty,
                        avg_price=result.avg_price,
                        pnl_pct=pnl_pct * 100,
                    )
                )

    def force_exit_day_positions(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        force_h, force_m = map(int, self.config.day_force_exit_at.split(":"))
        if (now.hour, now.minute) < (force_h, force_m):
            return

        with self._state_lock:
            for code, pos in list(self.state.open_positions.items()):
                if pos.type != "T":
                    continue
                try:
                    q = self.api.quote(code)
                except Exception:
                    q = {}
                price = parse_numeric(q.get("price"))
                if price is not None and self._should_carry_day_force_exit(
                    code=code,
                    pos=pos,
                    quote_price=price,
                    reason="FORCE",
                ):
                    continue
                result = exit_position(
                    self.api,
                    self.state,
                    code=code,
                    reason="FORCE",
                    now=now,
                    config=self.config,
                    on_order_accepted=lambda order, pos=pos: self._record_pending_exit_order(
                        order,
                        strategy_type=pos.type,
                    ),
                )
                if not result:
                    continue
                self.state.pending_exit_orders.pop(code, None)
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

    def _record_pending_exit_order(self, order: dict, *, strategy_type: str) -> None:
        code = str(order.get("code") or "").strip()
        if not code:
            return
        reason = str(order.get("reason") or "").strip().upper()
        order_id = str(order.get("order_id") or "").strip()
        qty = int(parse_numeric(order.get("qty")) or 0)
        with self._state_lock:
            self.state.pending_exit_orders[code] = {
                "strategy_type": str(strategy_type or "").strip().upper(),
                "reason": reason,
                "order_id": order_id,
                "qty": qty,
                "order_time": str(order.get("order_time") or "").strip(),
            }
            self._journal(
                "EXIT_ORDER_ACCEPTED",
                asof_date=self.state.trade_date,
                code=code,
                side="SELL",
                qty=qty,
                reason=reason,
                order_id=order_id,
                strategy_type=str(strategy_type or "").strip().upper(),
            )

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
        del now
        if reason != "SL" or pos.type != "T":
            return False

        review_key = self._day_stop_llm_review_key(code=code, pos=pos)
        already_reviewed = review_key in self.state.day_stop_llm_reviewed_positions
        intraday_meta = self._day_stop_intraday_meta(code=code)
        if not is_day_stop_review_candidate(
            config=self.config,
            position=pos,
            pnl_pct=pnl_pct,
            intraday_meta=intraday_meta,
            already_reviewed=already_reviewed,
        ):
            return False

        self.state.day_stop_llm_reviewed_positions.add(review_key)
        review = review_day_stop_with_llm(
            code=code,
            position=pos,
            quote_price=quote_price,
            intraday_meta=intraday_meta,
            config=self.config,
        )
        self._journal_day_stop_llm_review(
            code=code,
            review=review,
            intraday_meta=intraday_meta,
        )
        return review is not None and review.decision == "HOLD"

    def _should_carry_day_force_exit(
        self,
        *,
        code: str,
        pos: PositionState,
        quote_price: float,
        reason: str,
    ) -> bool:
        if reason != "FORCE" or pos.type != "T":
            return False

        review_key = self._day_stop_llm_review_key(code=code, pos=pos)
        carried_date = self.state.day_overnight_carry_positions.get(review_key)
        if carried_date == self.state.trade_date:
            return True
        if carried_date:
            return False

        already_reviewed = review_key in self.state.day_overnight_carry_reviewed_positions
        if not is_day_overnight_carry_candidate(
            config=self.config,
            position=pos,
            quote_price=quote_price,
            trade_date=self.state.trade_date,
            already_carried=already_reviewed,
        ):
            return False

        intraday_meta = self._day_stop_intraday_meta(code=code)
        self.state.day_overnight_carry_reviewed_positions.add(review_key)
        review = review_day_overnight_carry_with_llm(
            code=code,
            position=pos,
            quote_price=quote_price,
            intraday_meta=intraday_meta,
            config=self.config,
        )
        self._journal_day_overnight_carry_review(
            code=code,
            review=review,
            intraday_meta=intraday_meta,
        )
        if review is None or review.decision != "CARRY":
            return False

        self.state.day_overnight_carry_positions[review_key] = self.state.trade_date
        return True

    def _day_stop_intraday_meta(self, *, code: str) -> dict[str, object]:
        try:
            _, meta = passes_day_intraday_confirmation(
                self.api,
                trade_date=self.state.trade_date,
                code=code,
                config=self.config,
                logger=logger,
            )
            return dict(meta)
        except Exception:
            logger.warning("day stop intraday meta failed code=%s", code, exc_info=True)
            return {"reason": "FETCH_FAILED"}

    def _resolve_day_stop_loss_pct(self, *, code: str) -> float | None:
        multiplier = max(
            0.0,
            float(getattr(self.config, "day_stop_loss_volatility_multiplier", 0.0)),
        )
        if multiplier <= 0:
            return None

        meta = self._day_stop_intraday_meta(code=code)
        recent_range_pct = parse_numeric(meta.get("recent_range_pct"))
        if recent_range_pct is None or recent_range_pct <= 0:
            return None

        base_stop_abs = abs(float(self.config.day_stop_loss_pct))
        max_stop_abs = max(
            base_stop_abs,
            abs(float(getattr(self.config, "day_stop_loss_max_pct", self.config.day_stop_loss_pct))),
        )
        if max_stop_abs <= 0:
            return None

        adaptive_stop_abs = (float(recent_range_pct) / 100.0) * multiplier
        stop_abs = min(max(base_stop_abs, adaptive_stop_abs), max_stop_abs)
        return -stop_abs

    def _journal_day_stop_llm_review(
        self,
        *,
        code: str,
        review: DayStopReviewResult | None,
        intraday_meta: dict[str, object],
    ) -> None:
        decision = review.decision if review is not None else "EXIT"
        self._journal(
            "DAY_STOP_LLM_REVIEW",
            asof_date=self.state.trade_date,
            code=code,
            decision=decision,
            confidence=round(float(review.confidence), 4) if review is not None else 0.0,
            route=review.route if review is not None else "unavailable",
            review_reason=review.reason if review is not None else "LLM_UNAVAILABLE_OR_INVALID",
            intraday_reason=str(intraday_meta.get("reason") or ""),
            day_change_pct=intraday_meta.get("day_change_pct"),
            window_change_pct=intraday_meta.get("window_change_pct"),
            last_bar_change_pct=intraday_meta.get("last_bar_change_pct"),
            retrace_from_high_pct=intraday_meta.get("retrace_from_high_pct"),
        )

    def _journal_day_overnight_carry_review(
        self,
        *,
        code: str,
        review: DayOvernightCarryReviewResult | None,
        intraday_meta: dict[str, object],
    ) -> None:
        decision = review.decision if review is not None else "EXIT"
        self._journal(
            "DAY_OVERNIGHT_CARRY_REVIEW",
            asof_date=self.state.trade_date,
            code=code,
            decision=decision,
            confidence=round(float(review.confidence), 4) if review is not None else 0.0,
            route=review.route if review is not None else "unavailable",
            review_reason=review.reason if review is not None else "LLM_UNAVAILABLE_OR_INVALID",
            intraday_reason=str(intraday_meta.get("reason") or ""),
            day_change_pct=intraday_meta.get("day_change_pct"),
            window_change_pct=intraday_meta.get("window_change_pct"),
            last_bar_change_pct=intraday_meta.get("last_bar_change_pct"),
            retrace_from_high_pct=intraday_meta.get("retrace_from_high_pct"),
        )

    @staticmethod
    def _day_stop_llm_review_key(*, code: str, pos: PositionState) -> str:
        return f"{str(code).strip()}:{str(getattr(pos, 'entry_time', '')).strip()}"

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
