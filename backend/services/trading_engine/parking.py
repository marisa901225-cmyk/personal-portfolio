from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from .config import TradeEngineConfig
from .execution import enter_position, exit_position
from .interfaces import TradingAPI
from .notification_text import format_entry_message, format_exit_message
from .state import TradeState
from .utils import parse_hhmm


def parking_position_codes(state: TradeState) -> list[str]:
    return [
        code
        for code, pos in state.open_positions.items()
        if pos.type == "P"
    ]


def is_regular_market_open(now: datetime) -> bool:
    return (9, 0) <= (now.hour, now.minute) <= (15, 30)


def can_enter_risk_off_parking(config: TradeEngineConfig, now: datetime) -> bool:
    if not is_regular_market_open(now):
        return False
    close_h, close_m = parse_hhmm(config.no_new_entry_after)
    return (now.hour, now.minute) < (close_h, close_m)


def exit_risk_off_parking_positions(
    api: TradingAPI,
    state: TradeState,
    config: TradeEngineConfig,
    *,
    trade_date: str,
    now: datetime,
    reason: str,
    journal: Callable[..., None],
    notify_text: Callable[[str], None],
) -> None:
    for code in list(parking_position_codes(state)):
        pos = state.open_positions.get(code)
        if not pos:
            continue

        entry_price = float(pos.entry_price or 0.0)
        result = exit_position(
            api,
            state,
            code=code,
            reason=reason,
            now=now,
        )
        if not result:
            continue

        pnl_pct = 0.0
        if entry_price > 0:
            pnl_pct = (result.avg_price / entry_price - 1.0) * 100.0

        journal(
            "EXIT_FILL",
            asof_date=trade_date,
            code=code,
            side="SELL",
            qty=result.qty,
            avg_price=result.avg_price,
            pnl_pct=round(pnl_pct, 4),
            reason=reason,
            strategy_type="P",
        )
        notify_text(
            format_exit_message(
                strategy="P",
                reason=reason,
                code=code,
                qty=result.qty,
                avg_price=result.avg_price,
                pnl_pct=pnl_pct,
            )
        )


def manage_risk_off_parking(
    api: TradingAPI,
    state: TradeState,
    config: TradeEngineConfig,
    *,
    trade_date: str,
    now: datetime,
    regime: str,
    journal: Callable[..., None],
    notify_text: Callable[[str], None],
) -> None:
    parking_codes = parking_position_codes(state)
    parking_code = str(config.risk_off_parking_code).strip()
    parking_enabled = bool(config.risk_off_parking_enabled and parking_code)
    existing_parking = state.open_positions.get(parking_code)

    if regime != "RISK_OFF" or not parking_enabled:
        if not parking_codes or not is_regular_market_open(now):
            return
        reason = "RISK_ON" if regime != "RISK_OFF" else "PARKING_DISABLED"
        exit_risk_off_parking_positions(
            api,
            state,
            config,
            trade_date=trade_date,
            now=now,
            reason=reason,
            journal=journal,
            notify_text=notify_text,
        )
        return

    if parking_codes and parking_code not in parking_codes and is_regular_market_open(now):
        exit_risk_off_parking_positions(
            api,
            state,
            config,
            trade_date=trade_date,
            now=now,
            reason="PARKING_ROTATE",
            journal=journal,
            notify_text=notify_text,
        )
        parking_codes = parking_position_codes(state)
        if parking_codes:
            return

    if not can_enter_risk_off_parking(config, now):
        return
    if existing_parking is None and len(state.open_positions) >= config.max_total_positions:
        return

    result = enter_position(
        api,
        state,
        position_type="P",
        code=parking_code,
        cash_ratio=config.risk_off_parking_cash_ratio,
        asof_date=trade_date,
        now=now,
        order_type=config.risk_off_parking_order_type,
    )
    if not result:
        return

    sizing = getattr(result, "sizing", None) or {}
    if not isinstance(sizing, dict):
        sizing = {}
    journal(
        "ENTRY_FILL",
        asof_date=trade_date,
        code=parking_code,
        side="BUY",
        qty=result.qty,
        avg_price=result.avg_price,
        strategy_type="P",
        regime=regime,
        **dict(sizing),
    )
    notify_text(
        format_entry_message(
            strategy="P",
            code=parking_code,
            qty=result.qty,
            avg_price=result.avg_price,
            regime=regime,
        )
    )
