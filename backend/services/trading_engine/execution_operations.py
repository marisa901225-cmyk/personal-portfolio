from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from .config import TradeEngineConfig
from .execution_support import (
    FillResult,
    can_retry_buy_with_higher_price,
    extract_order_id,
    get_broker_position_snapshot,
    is_buy_order_side,
    next_buy_retry_price,
    normalize_buy_limit_price,
    parse_order_time,
    resolve_buy_fill,
    resolve_sell_fill,
)
from .execution_sizing import (
    calc_buy_qty,
    resolve_buy_budget_cash,
    resolve_buy_sizing,
    resolve_sell_sizing,
)
from .interfaces import TradingAPI
from .state import (
    PositionState,
    TradeState,
    get_day_reentry_blocked_codes,
    mark_day_stoploss_today,
    mark_swing_time_excluded,
    record_day_stoploss_failure,
)
from .types import OrderPayload
from .utils import parse_numeric

logger = logging.getLogger(__name__)

_BUY_BUFFER_RATIO = 0.005
_BUY_BUFFER_KRW = 5_000
_BUY_RETRY_MAX = 1
_BUY_PRICE_RETRY_MAX = 1
_INSUFFICIENT_CASH_MESSAGES = (
    "주문가능금액",
    "주문 가능 금액",
    "초과",
    "insufficient",
    "not enough",
)


def enter_position(
    api: TradingAPI,
    state: TradeState,
    *,
    position_type: str,
    code: str,
    cash_ratio: float,
    asof_date: str,
    now: datetime,
    order_type: str = "MKT",
    price: int | None = None,
    budget_cash_cap: float | None = None,
    on_order_accepted: Callable[[OrderPayload], None] | None = None,
) -> FillResult | None:
    existing_position = state.open_positions.get(code)
    broker_before_qty, _ = get_broker_position_snapshot(api=api, code=code)
    if code in state.blacklist_today:
        return None
    if position_type == "T" and code in get_day_reentry_blocked_codes(state):
        return None
    if code in state.pending_entry_orders:
        return None
    if existing_position is not None:
        return None

    quote = api.quote(code)
    price_now = parse_numeric(quote.get("price"))
    if price_now is None or price_now <= 0:
        return None

    normalized_order_type = str(order_type or "").strip().lower()
    if normalized_order_type == "limit" and (price is None or int(price) <= 0):
        fallback_limit_price = normalize_buy_limit_price(int(price_now))
        logger.warning(
            "enter_position: missing limit price; using quote-derived fallback code=%s order_type=%s quote_price=%s->%s",
            code,
            order_type,
            price_now,
            fallback_limit_price,
        )
        price = fallback_limit_price
    if price is not None and price > 0 and normalized_order_type in {"limit", "best"}:
        normalized_price = normalize_buy_limit_price(int(price))
        if normalized_price != int(price):
            logger.warning(
                "enter_position: normalized invalid limit price code=%s order_type=%s price=%s->%s",
                code,
                order_type,
                price,
                normalized_price,
            )
        price = normalized_price

    fallback_cash = float(api.cash_available())
    sizing = resolve_buy_sizing(
        api=api,
        code=code,
        order_type=order_type,
        price=price,
        fallback_cash=fallback_cash,
        fallback_price=float(price_now),
    )
    budget_cash = resolve_buy_budget_cash(
        cash=sizing.cash,
        cash_ratio=cash_ratio,
        budget_cash_cap=budget_cash_cap,
    )
    qty = calc_buy_qty(budget_cash=budget_cash, price_now=sizing.price_now)
    if qty < 1:
        return None

    sizing_meta = {
        "cash_available_snapshot": int(fallback_cash),
        "sizing_cash": int(sizing.cash),
        "quote_price": float(price_now),
        "sizing_price": float(sizing.price_now),
        "budget_cash": int(budget_cash),
        "max_qty": int(sizing.max_qty) if sizing.max_qty is not None else None,
        "requested_qty": int(qty),
        "cash_ratio": float(cash_ratio),
        "order_type": str(order_type),
    }
    if sizing.cash < fallback_cash:
        logger.info(
            "enter_position: broker buyable cash below balance code=%s balance_cash=%.0f buyable_cash=%.0f sizing_price=%.0f ratio=%.2f qty=%d",
            code,
            fallback_cash,
            sizing.cash,
            sizing.price_now,
            cash_ratio,
            qty,
        )

    attempted_qty = qty
    attempted_price = int(price) if price is not None else None
    cash_retry_count = 0
    price_retry_count = 0
    resp: OrderPayload | None = None
    while True:
        resp = api.place_order(
            side="BUY",
            code=code,
            qty=attempted_qty,
            order_type=order_type,
            price=attempted_price,
        )
        if resp.get("success") is not False:
            break

        msg = str(resp.get("msg") or "")
        logger.warning(
            "enter_position: broker rejected order code=%s qty=%d order_type=%s price=%s order_id=%s msg=%s",
            code,
            attempted_qty,
            order_type,
            attempted_price,
            extract_order_id(resp),
            msg,
        )

        if is_insufficient_cash_rejection(msg) and cash_retry_count < _BUY_RETRY_MAX:
            cash_retry_count += 1
            refreshed_sizing = resolve_buy_sizing(
                api=api,
                code=code,
                order_type=order_type,
                price=attempted_price,
                fallback_cash=float(api.cash_available()),
                fallback_price=float(attempted_price or price_now),
            )
            refreshed_budget_cash = resolve_buy_budget_cash(
                cash=refreshed_sizing.cash,
                cash_ratio=cash_ratio,
                budget_cash_cap=budget_cash_cap,
            )
            next_qty = calc_buy_qty(
                budget_cash=refreshed_budget_cash,
                price_now=refreshed_sizing.price_now,
                extra_buffer_ratio=_BUY_BUFFER_RATIO * (cash_retry_count + 1),
                extra_buffer_krw=_BUY_BUFFER_KRW * (cash_retry_count + 1),
            )
            if refreshed_sizing.max_qty is not None:
                next_qty = min(next_qty, refreshed_sizing.max_qty)
            next_qty = min(next_qty, attempted_qty - 1)
            if next_qty < 1:
                logger.warning(
                    "enter_position: insufficient buying power after retry code=%s last_qty=%d cash=%.0f price=%s msg=%s",
                    code,
                    attempted_qty,
                    refreshed_sizing.cash,
                    attempted_price,
                    msg,
                )
                return None

            logger.warning(
                "enter_position: reducing qty after insufficient cash code=%s qty=%d->%d cash=%.0f price=%s msg=%s",
                code,
                attempted_qty,
                next_qty,
                refreshed_sizing.cash,
                attempted_price,
                msg,
            )
            attempted_qty = next_qty
            sizing_meta["sizing_cash"] = int(refreshed_sizing.cash)
            sizing_meta["sizing_price"] = float(refreshed_sizing.price_now)
            sizing_meta["budget_cash"] = int(refreshed_budget_cash)
            sizing_meta["max_qty"] = int(refreshed_sizing.max_qty) if refreshed_sizing.max_qty is not None else None
            sizing_meta["requested_qty"] = int(next_qty)
            continue

        if can_retry_buy_with_higher_price(order_type=order_type, price=attempted_price) and price_retry_count < _BUY_PRICE_RETRY_MAX:
            price_retry_count += 1
            next_price = next_buy_retry_price(int(attempted_price))
            refreshed_sizing = resolve_buy_sizing(
                api=api,
                code=code,
                order_type=order_type,
                price=next_price,
                fallback_cash=float(api.cash_available()),
                fallback_price=float(next_price),
            )
            refreshed_budget_cash = resolve_buy_budget_cash(
                cash=refreshed_sizing.cash,
                cash_ratio=cash_ratio,
                budget_cash_cap=budget_cash_cap,
            )
            next_qty = calc_buy_qty(
                budget_cash=refreshed_budget_cash,
                price_now=refreshed_sizing.price_now,
            )
            if refreshed_sizing.max_qty is not None:
                next_qty = min(next_qty, refreshed_sizing.max_qty)
            next_qty = min(next_qty, attempted_qty)
            if next_qty < 1:
                logger.warning(
                    "enter_position: higher-price retry skipped due to zero qty code=%s next_price=%s cash=%.0f msg=%s",
                    code,
                    next_price,
                    refreshed_sizing.cash,
                    msg,
                )
                return None

            logger.warning(
                "enter_position: retrying with higher price code=%s qty=%d->%d price=%s->%s msg=%s",
                code,
                attempted_qty,
                next_qty,
                attempted_price,
                next_price,
                msg,
            )
            attempted_price = next_price
            attempted_qty = next_qty
            sizing_meta["sizing_cash"] = int(refreshed_sizing.cash)
            sizing_meta["sizing_price"] = float(refreshed_sizing.price_now)
            sizing_meta["budget_cash"] = int(refreshed_budget_cash)
            sizing_meta["max_qty"] = int(refreshed_sizing.max_qty) if refreshed_sizing.max_qty is not None else None
            sizing_meta["requested_qty"] = int(next_qty)
            continue

        return None

    if resp is None:
        return None

    filled_qty, avg_price = resolve_buy_fill(
        api=api,
        code=code,
        fallback_price=float(price_now),
        response=resp,
        broker_before_qty=broker_before_qty,
    )
    if filled_qty <= 0 or avg_price is None or avg_price <= 0:
        if on_order_accepted is not None:
            on_order_accepted(
                {
                    "code": code,
                    "side": "BUY",
                    "qty": attempted_qty,
                    "order_id": extract_order_id(resp),
                    "order_time": resp.get("order_time") or resp.get("ord_tmd"),
                    "order_type": order_type,
                    "price": attempted_price,
                    "raw": resp,
                }
            )
        logger.info(
            "enter_position: order accepted but no confirmed fill yet code=%s qty=%d order_type=%s price=%s order_id=%s msg=%s",
            code,
            attempted_qty,
            order_type,
            attempted_price,
            extract_order_id(resp),
            resp.get("msg"),
        )
        return None

    order_id = extract_order_id(resp)

    state.pending_entry_orders.pop(code, None)
    state.open_positions[code] = PositionState(
        type=position_type,
        entry_time=now.isoformat(timespec="seconds"),
        entry_price=float(avg_price),
        qty=filled_qty,
        highest_price=float(avg_price),
        entry_date=asof_date,
        locked_profit_pct=None,
        bars_held=0,
    )
    if position_type != "P":
        state.blacklist_today.add(code)

    if position_type == "S":
        state.swing_entries_today += 1
        state.swing_entries_week += 1
    elif position_type == "T":
        state.day_entries_today += 1

    return FillResult(
        code=code,
        side="BUY",
        qty=filled_qty,
        avg_price=float(avg_price),
        order_id=order_id,
        raw=resp,
        sizing=sizing_meta,
    )


def exit_position(
    api: TradingAPI,
    state: TradeState,
    *,
    code: str,
    reason: str,
    now: datetime,
    config: TradeEngineConfig | None = None,
    order_type: str = "MKT",
    price: int | None = None,
    on_order_accepted: Callable[[OrderPayload], None] | None = None,
) -> FillResult | None:
    if code in state.pending_exit_orders:
        return None
    pos = state.open_positions.get(code)
    if not pos:
        return None
    broker_before_qty, _ = get_broker_position_snapshot(api=api, code=code)

    sell_sizing = resolve_sell_sizing(api=api, code=code)
    requested_qty = pos.qty
    if sell_sizing.max_qty is not None:
        requested_qty = min(requested_qty, sell_sizing.max_qty)
    if requested_qty < 1:
        logger.warning("exit_position: no sellable quantity code=%s local_qty=%d", code, pos.qty)
        return None
    if requested_qty < pos.qty:
        logger.warning(
            "exit_position: capping sell qty by broker capacity code=%s local_qty=%d sellable_qty=%d",
            code,
            pos.qty,
            requested_qty,
        )

    resp = api.place_order(side="SELL", code=code, qty=requested_qty, order_type=order_type, price=price)
    if resp.get("success") is False:
        logger.warning(
            "exit_position: broker rejected order code=%s qty=%d msg=%s",
            code,
            requested_qty,
            resp.get("msg"),
        )
        return None
    quote = api.quote(code)
    market_price = parse_numeric(quote.get("price")) or pos.entry_price

    filled_qty, avg_price = resolve_sell_fill(
        api=api,
        code=code,
        response=resp,
        broker_before_qty=broker_before_qty,
        requested_qty=requested_qty,
        fallback_price=float(market_price),
    )
    if filled_qty <= 0 or avg_price is None or avg_price <= 0:
        if on_order_accepted is not None:
            on_order_accepted(
                {
                    "code": code,
                    "side": "SELL",
                    "qty": requested_qty,
                    "reason": reason,
                    "order_id": extract_order_id(resp),
                    "order_time": resp.get("order_time") or resp.get("ord_tmd"),
                    "order_type": order_type,
                    "price": price,
                    "raw": resp,
                }
            )
        logger.info(
            "exit_position: order accepted but no confirmed sell fill yet code=%s qty=%d order_id=%s",
            code,
            requested_qty,
            extract_order_id(resp),
        )
        return None

    logger.info(
        "exit_position: %s filled qty=%d avg_price=%.0f (market=%.0f)",
        code, filled_qty, avg_price, market_price,
    )

    pnl = (float(avg_price) - pos.entry_price) * filled_qty
    state.realized_pnl_today += pnl
    state.realized_pnl_total += pnl
    if pnl < 0:
        state.consecutive_losses_today += 1
    else:
        state.consecutive_losses_today = 0
    if pos.type == "T":
        if pnl > 0:
            state.day_wins_today += 1
        elif pnl < 0:
            state.day_losses_today += 1

    if pos.type == "T" and reason == "SL":
        exclude_after_losses = 3
        if config is not None:
            exclude_after_losses = max(1, int(config.day_stoploss_exclude_after_losses))
        loss_count = record_day_stoploss_failure(
            state,
            code=code,
            exclude_after_losses=exclude_after_losses,
        )
        logger.info(
            "day stoploss recorded code=%s count=%d exclude_after=%d excluded=%s",
            code,
            loss_count,
            exclude_after_losses,
            code in state.day_stoploss_excluded_codes,
        )
        mark_day_stoploss_today(
            state,
            code=code,
        )
    if pos.type == "S" and reason == "TIME":
        mark_swing_time_excluded(
            state,
            code=code,
        )

    remaining_qty = pos.qty - filled_qty
    if remaining_qty <= 0:
        state.open_positions.pop(code, None)
    else:
        pos.qty = remaining_qty

    return FillResult(
        code=code,
        side="SELL",
        qty=filled_qty,
        avg_price=float(avg_price),
        reason=reason,
        order_id=extract_order_id(resp),
        raw=resp,
    )


def handle_open_orders(
    api: TradingAPI,
    *,
    timeout_sec: int = 30,
    now: datetime | None = None,
) -> dict[str, int]:
    cancelled = 0
    skipped_recent = 0
    skipped_unknown_time = 0
    skipped_exit = 0
    current_time = now or datetime.now()
    for order in api.open_orders() or []:
        order_id = extract_order_id(order)
        if not order_id:
            continue

        status = str(order.get("status") or order.get("ord_stat") or "").upper()
        if status in {"FILLED", "DONE", "CANCELED", "CANCELLED"}:
            continue

        remaining_qty = parse_numeric(order.get("remaining_qty") or order.get("psbl_qty"))
        if remaining_qty is not None and remaining_qty <= 0:
            continue
        if not is_buy_order_side(order):
            skipped_exit += 1
            continue

        order_time = parse_order_time(order, now=current_time)
        if timeout_sec > 0:
            if order_time is None:
                skipped_unknown_time += 1
                continue
            if (current_time - order_time) < timedelta(seconds=timeout_sec):
                skipped_recent += 1
                continue

        try:
            api.cancel_order(order_id)
            cancelled += 1
        except Exception as exc:
            logger.warning("cancel_order failed order_id=%s error=%s", order_id, exc)
            continue

    return {
        "cancelled": cancelled,
        "skipped_recent": skipped_recent,
        "skipped_unknown_time": skipped_unknown_time,
        "skipped_exit": skipped_exit,
    }


def increment_bars_held(state: TradeState) -> None:
    for pos in state.open_positions.values():
        if pos.type == "S":
            pos.bars_held += 1


def is_insufficient_cash_rejection(message: str) -> bool:
    lowered = message.lower()
    return any(token.lower() in lowered for token in _INSUFFICIENT_CASH_MESSAGES)
