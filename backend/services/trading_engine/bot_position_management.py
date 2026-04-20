from __future__ import annotations

import logging
from datetime import datetime

from .execution import exit_position
from .parking import manage_risk_off_parking
from .position_helpers import (
    is_swing_trend_broken,
    lock_profitable_existing_position,
    reconcile_state_with_broker_positions,
)
from .risk import should_exit_position
from .utils import parse_numeric

logger = logging.getLogger(__name__)


class BotPositionManagementMixin:
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
