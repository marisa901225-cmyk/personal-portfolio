from __future__ import annotations

from datetime import datetime

from .execution import FillResult
from .notification_text import format_pending_entry_message
from .state import PositionState
from .utils import parse_numeric


def recover_failed_buy_attempt(
    bot,
    *,
    code: str,
    strategy_type: str,
    now: datetime,
    regime: str,
    logger,
) -> tuple[FillResult | None, dict | None]:
    synced_result = sync_broker_filled_position(
        bot,
        code=code,
        strategy_type=strategy_type,
        now=now,
        regime=regime,
        logger=logger,
    )
    if synced_result is not None:
        return synced_result, None

    pending_order = find_pending_buy_order(bot, code=code, logger=logger)
    if pending_order is not None:
        bot.state.pending_entry_orders[str(code).strip()] = str(strategy_type).strip().upper()
        order_id = str(pending_order.get("order_id") or "")
        order_qty = int(parse_numeric(pending_order.get("qty")) or 0)
        remaining_qty = int(parse_numeric(pending_order.get("remaining_qty")) or 0)
        order_price = parse_numeric(pending_order.get("price"))
        bot._notify_text(
            format_pending_entry_message(
                strategy=strategy_type,
                code=code,
                order_id=order_id or "",
                qty=order_qty,
                remaining_qty=remaining_qty,
                price=int(order_price) if order_price else 0,
            )
        )
        return None, pending_order

    return None, None


def record_pending_entry_order(bot, order: dict, *, strategy_type: str) -> None:
    code = str(order.get("code") or "").strip()
    normalized_type = str(strategy_type or "").strip().upper()
    if not code or normalized_type not in {"S", "T", "P"}:
        return

    bot.state.pending_entry_orders[code] = normalized_type
    order_id = str(order.get("order_id") or "").strip()
    qty = int(parse_numeric(order.get("qty")) or 0)
    price = int(parse_numeric(order.get("price")) or 0)
    bot._journal(
        "ENTRY_ORDER_ACCEPTED",
        asof_date=bot.state.trade_date,
        code=code,
        side="BUY",
        qty=qty,
        order_id=order_id,
        strategy_type=normalized_type,
    )
    bot._notify_text(
        format_pending_entry_message(
            strategy=normalized_type,
            code=code,
            order_id=order_id,
            qty=qty,
            remaining_qty=qty,
            price=price,
        )
    )


def sync_broker_filled_position(
    bot,
    *,
    code: str,
    strategy_type: str,
    now: datetime,
    regime: str,
    logger,
) -> FillResult | None:
    normalized_code = str(code or "").strip()
    if not normalized_code:
        return None

    try:
        broker_positions = bot.api.positions() or []
    except Exception:
        logger.warning("broker position recheck failed code=%s", normalized_code, exc_info=True)
        return None

    for item in broker_positions:
        broker_code = str(item.get("code") or item.get("pdno") or "").strip()
        qty = int(parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0)
        if broker_code != normalized_code or qty <= 0:
            continue

        avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
        current_price = parse_numeric(item.get("current_price") or item.get("prpr"))
        resolved_price = float(avg_price or current_price or 0.0)
        if resolved_price <= 0:
            quote = bot.api.quote(normalized_code)
            resolved_price = float(parse_numeric(quote.get("price")) or 0.0)
        if resolved_price <= 0:
            return None

        existing = bot.state.open_positions.get(normalized_code)
        if existing is None:
            bot.state.open_positions[normalized_code] = PositionState(
                type=strategy_type,
                entry_time=now.isoformat(timespec="seconds"),
                entry_price=resolved_price,
                qty=qty,
                highest_price=resolved_price,
                entry_date=bot.state.trade_date,
                locked_profit_pct=None,
                bars_held=0,
            )
            if strategy_type == "S":
                bot.state.swing_entries_today += 1
                bot.state.swing_entries_week += 1
            elif strategy_type == "T":
                bot.state.day_entries_today += 1
            bot.state.blacklist_today.add(normalized_code)
            bot._journal(
                "STATE_RECONCILE_ADD",
                asof_date=bot.state.trade_date,
                code=normalized_code,
                qty=qty,
                avg_price=resolved_price,
                reason="BROKER_POSITION_FOUND_AFTER_ENTRY_ATTEMPT",
                strategy_type=strategy_type,
                regime=regime,
            )
        else:
            existing.qty = qty
            existing.entry_price = resolved_price
            existing.highest_price = max(float(existing.highest_price or 0.0), resolved_price)

        bot.state.pending_entry_orders.pop(normalized_code, None)

        return FillResult(
            code=normalized_code,
            side="BUY",
            qty=qty,
            avg_price=resolved_price,
            reason="BROKER_SYNC",
            raw=dict(item) if isinstance(item, dict) else None,
        )

    return None


def find_pending_buy_order(bot, *, code: str, logger) -> dict | None:
    normalized_code = str(code or "").strip()
    if not normalized_code:
        return None

    try:
        open_orders = bot.api.open_orders() or []
    except Exception:
        logger.warning("open_orders recheck failed code=%s", normalized_code, exc_info=True)
        return None

    for order in open_orders:
        order_code = str(order.get("code") or order.get("pdno") or "").strip()
        if order_code != normalized_code:
            continue
        side = str(order.get("side") or order.get("sll_buy_dvsn_cd") or "").strip().lower()
        if side not in {"buy", "02"}:
            continue
        remaining_qty = parse_numeric(order.get("remaining_qty") or order.get("psbl_qty"))
        if remaining_qty is not None and remaining_qty <= 0:
            continue
        return dict(order)
    return None


def refresh_pending_entry_orders(bot, *, logger) -> None:
    if not bot.state.pending_entry_orders:
        return

    try:
        open_orders = bot.api.open_orders() or []
    except Exception:
        logger.warning("open_orders refresh failed for pending entry sync", exc_info=True)
        return

    pending_codes: set[str] = set()
    for order in open_orders:
        order_code = str(order.get("code") or order.get("pdno") or "").strip()
        if not order_code:
            continue
        side = str(order.get("side") or order.get("sll_buy_dvsn_cd") or "").strip().lower()
        if side not in {"buy", "02"}:
            continue
        remaining_qty = parse_numeric(order.get("remaining_qty") or order.get("psbl_qty"))
        if remaining_qty is not None and remaining_qty <= 0:
            continue
        pending_codes.add(order_code)

    for code in list(bot.state.pending_entry_orders):
        if code in bot.state.open_positions or code in pending_codes:
            continue
        bot.state.pending_entry_orders.pop(code, None)


__all__ = [
    "find_pending_buy_order",
    "recover_failed_buy_attempt",
    "record_pending_entry_order",
    "refresh_pending_entry_orders",
    "sync_broker_filled_position",
]
