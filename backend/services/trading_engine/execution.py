from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import TradeEngineConfig
from .interfaces import BuyOrderInfoAPI, SellOrderInfoAPI, TradingAPI
from .state import (
    PositionState,
    TradeState,
    mark_swing_time_excluded,
    record_day_stoploss_failure,
)
from .utils import parse_numeric

logger = logging.getLogger(__name__)

_BUY_BUFFER_RATIO = 0.005
_BUY_BUFFER_KRW = 5_000
_BUY_RETRY_MAX = 1
_INSUFFICIENT_CASH_MESSAGES = (
    "주문가능금액",
    "주문 가능 금액",
    "초과",
    "insufficient",
    "not enough",
)


@dataclass(slots=True)
class FillResult:
    code: str
    side: str
    qty: int
    avg_price: float
    reason: str | None = None
    order_id: str | None = None
    raw: dict[str, Any] | None = None
    sizing: dict[str, Any] | None = None


@dataclass(slots=True)
class BuySizingSnapshot:
    cash: float
    price_now: float
    max_qty: int | None = None


@dataclass(slots=True)
class SellSizingSnapshot:
    max_qty: int | None = None



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
) -> FillResult | None:
    existing_position = state.open_positions.get(code)
    if code in state.blacklist_today:
        return None
    if position_type == "T" and code in state.day_stoploss_excluded_codes:
        return None
    if existing_position is not None and not (
        position_type == "P" and existing_position.type == "P"
    ):
        return None

    quote = api.quote(code)
    price_now = parse_numeric(quote.get("price"))
    if price_now is None or price_now <= 0:
        return None

    fallback_cash = float(api.cash_available())
    sizing = _resolve_buy_sizing(
        api=api,
        code=code,
        order_type=order_type,
        price=price,
        fallback_cash=fallback_cash,
        fallback_price=float(price_now),
    )
    budget_cash = _resolve_buy_budget_cash(
        cash=sizing.cash,
        cash_ratio=cash_ratio,
        budget_cash_cap=budget_cash_cap,
    )
    qty = _calc_buy_qty(budget_cash=budget_cash, price_now=sizing.price_now)
    if sizing.max_qty is not None:
        qty = min(qty, sizing.max_qty)
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
    resp: dict[str, Any] | None = None
    for retry_idx in range(_BUY_RETRY_MAX + 1):
        resp = api.place_order(
            side="BUY",
            code=code,
            qty=attempted_qty,
            order_type=order_type,
            price=price,
        )
        if resp.get("success") is not False:
            break

        msg = str(resp.get("msg") or "")
        if retry_idx >= _BUY_RETRY_MAX or not _is_insufficient_cash_rejection(msg):
            logger.warning(
                "enter_position: broker rejected order code=%s qty=%d msg=%s",
                code,
                attempted_qty,
                msg,
            )
            return None

        refreshed_sizing = _resolve_buy_sizing(
            api=api,
            code=code,
            order_type=order_type,
            price=price,
            fallback_cash=float(api.cash_available()),
            fallback_price=float(price_now),
        )
        refreshed_budget_cash = _resolve_buy_budget_cash(
            cash=refreshed_sizing.cash,
            cash_ratio=cash_ratio,
            budget_cash_cap=budget_cash_cap,
        )
        next_qty = _calc_buy_qty(
            budget_cash=refreshed_budget_cash,
            price_now=refreshed_sizing.price_now,
            extra_buffer_ratio=_BUY_BUFFER_RATIO * (retry_idx + 2),
            extra_buffer_krw=_BUY_BUFFER_KRW * (retry_idx + 2),
        )
        if refreshed_sizing.max_qty is not None:
            next_qty = min(next_qty, refreshed_sizing.max_qty)
        next_qty = min(next_qty, attempted_qty - 1)
        if next_qty < 1:
            logger.warning(
                "enter_position: insufficient buying power after retry code=%s last_qty=%d cash=%.0f msg=%s",
                code,
                attempted_qty,
                refreshed_sizing.cash,
                msg,
            )
            return None

        logger.warning(
            "enter_position: reducing qty after insufficient cash code=%s qty=%d->%d cash=%.0f msg=%s",
            code,
            attempted_qty,
            next_qty,
            refreshed_sizing.cash,
            msg,
        )
        attempted_qty = next_qty
        sizing_meta["sizing_cash"] = int(refreshed_sizing.cash)
        sizing_meta["sizing_price"] = float(refreshed_sizing.price_now)
        sizing_meta["budget_cash"] = int(refreshed_budget_cash)
        sizing_meta["max_qty"] = int(refreshed_sizing.max_qty) if refreshed_sizing.max_qty is not None else None
        sizing_meta["requested_qty"] = int(next_qty)

    if resp is None:
        return None

    filled_qty_num = parse_numeric(resp.get("filled_qty"))
    if filled_qty_num is None:
        filled_qty = attempted_qty
    else:
        filled_qty = int(filled_qty_num)

    if filled_qty <= 0:
        logger.warning("enter_position: zero fill for %s", code)
        return None

    avg_price_num = parse_numeric(resp.get("avg_price"))
    avg_price = float(avg_price_num) if avg_price_num is not None else price_now
    order_id = _extract_order_id(resp)

    if existing_position is not None and position_type == "P" and existing_position.type == "P":
        total_qty = existing_position.qty + filled_qty
        total_cost = (existing_position.entry_price * existing_position.qty) + (float(avg_price) * filled_qty)
        existing_position.entry_time = now.isoformat(timespec="seconds")
        existing_position.entry_price = total_cost / total_qty
        existing_position.qty = total_qty
        existing_position.highest_price = max(float(existing_position.highest_price or 0.0), float(avg_price))
        existing_position.entry_date = asof_date
    else:
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
) -> FillResult | None:
    pos = state.open_positions.get(code)
    if not pos:
        return None

    sell_sizing = _resolve_sell_sizing(api=api, code=code)
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

    filled_qty_num = parse_numeric(resp.get("filled_qty"))
    if filled_qty_num is None:
        filled_qty = requested_qty
    else:
        filled_qty = int(filled_qty_num)

    if filled_qty <= 0:
        logger.warning("exit_position: zero fill for %s", code)
        return None

    # 1순위: KIS 실현손익 API로 실제 체결 평단가 확정 (앱과 동일한 값)
    avg_price: float | None = None
    if hasattr(api, "get_today_sell_avg_price"):
        try:
            avg_price = api.get_today_sell_avg_price(code)
        except Exception as exc:
            logger.warning("exit_position: get_today_sell_avg_price failed code=%s err=%s", code, exc)

    # 2순위: 주문 응답의 avg_price
    if avg_price is None or avg_price <= 0:
        avg_price_num = parse_numeric(resp.get("avg_price"))
        avg_price = float(avg_price_num) if avg_price_num is not None else market_price

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
        order_id=_extract_order_id(resp),
        raw=resp,
    )


def handle_open_orders(
    api: TradingAPI,
    *,
    timeout_sec: int = 30,
) -> dict[str, int]:
    del timeout_sec  # open_orders schema is broker-specific; best-effort conservative handling.

    cancelled = 0
    for order in api.open_orders() or []:
        order_id = _extract_order_id(order)
        if not order_id:
            continue

        status = str(order.get("status") or order.get("ord_stat") or "").upper()
        if status in {"FILLED", "DONE", "CANCELED", "CANCELLED"}:
            continue

        try:
            api.cancel_order(order_id)
            cancelled += 1
        except Exception as exc:
            logger.warning("cancel_order failed order_id=%s error=%s", order_id, exc)
            continue

    return {"cancelled": cancelled}


def increment_bars_held(state: TradeState) -> None:
    for pos in state.open_positions.values():
        if pos.type == "S":
            pos.bars_held += 1


def _extract_order_id(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    for key in ("order_id", "odno", "id", "ord_no"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def _resolve_buy_sizing(
    *,
    api: TradingAPI,
    code: str,
    order_type: str,
    price: int | None,
    fallback_cash: float,
    fallback_price: float,
) -> BuySizingSnapshot:
    snapshot = BuySizingSnapshot(
        cash=max(0.0, fallback_cash),
        price_now=max(0.0, fallback_price),
    )
    if not isinstance(api, BuyOrderInfoAPI):
        return snapshot

    query_price = int(price or 0) or int(fallback_price)
    try:
        info = api.buy_order_capacity(
            code=code,
            order_type=order_type,
            price=query_price,
        )
    except Exception as exc:
        logger.warning(
            "buy_order_capacity lookup failed code=%s type=%s price=%s error=%s",
            code,
            order_type,
            query_price,
            exc,
        )
        return snapshot

    buyable_cash = parse_numeric(info.get("nrcvb_buy_amt"))
    if buyable_cash is None or buyable_cash <= 0:
        buyable_cash = parse_numeric(info.get("ord_psbl_cash"))
    if buyable_cash is not None and buyable_cash > 0:
        snapshot.cash = float(buyable_cash)

    calc_price = parse_numeric(info.get("psbl_qty_calc_unpr"))
    if _should_use_broker_calc_price(order_type=order_type, requested_price=price) and calc_price is not None and calc_price > 0:
        snapshot.price_now = float(calc_price)

    max_qty = parse_numeric(info.get("nrcvb_buy_qty"))
    if max_qty is None or max_qty <= 0:
        max_qty = parse_numeric(info.get("max_buy_qty"))
    if max_qty is not None and max_qty > 0:
        snapshot.max_qty = int(max_qty)

    return snapshot


def _resolve_sell_sizing(
    *,
    api: TradingAPI,
    code: str,
) -> SellSizingSnapshot:
    snapshot = SellSizingSnapshot()
    if not isinstance(api, SellOrderInfoAPI):
        return snapshot

    try:
        info = api.sell_order_capacity(code)
    except Exception as exc:
        logger.warning("sell_order_capacity lookup failed code=%s error=%s", code, exc)
        return snapshot

    sellable_qty = parse_numeric(info.get("ord_psbl_qty"))
    if sellable_qty is not None and sellable_qty >= 0:
        snapshot.max_qty = int(sellable_qty)
    return snapshot


def _resolve_buy_budget_cash(
    *,
    cash: float,
    cash_ratio: float,
    budget_cash_cap: float | None = None,
) -> float:
    ratio_budget = max(0.0, cash * cash_ratio)
    if budget_cash_cap is None or budget_cash_cap <= 0:
        return ratio_budget
    return max(0.0, min(cash, float(budget_cash_cap)))


def _calc_buy_qty(
    *,
    budget_cash: float,
    price_now: float,
    extra_buffer_ratio: float = 0.0,
    extra_buffer_krw: int = 0,
) -> int:
    buffer_cash = max(
        extra_buffer_krw,
        budget_cash * extra_buffer_ratio,
    )
    usable_budget = max(0.0, budget_cash - buffer_cash)
    qty = int(usable_budget // price_now)
    if qty < 1 and budget_cash >= price_now:
        return int(budget_cash // price_now)
    return qty


def _should_use_broker_calc_price(*, order_type: str, requested_price: int | None) -> bool:
    if requested_price is not None and requested_price > 0:
        return True

    normalized = str(order_type or "").strip().lower()
    return normalized in {"market", "mkt", "conditional"}


def _is_insufficient_cash_rejection(message: str) -> bool:
    lowered = message.lower()
    return any(token.lower() in lowered for token in _INSUFFICIENT_CASH_MESSAGES)
