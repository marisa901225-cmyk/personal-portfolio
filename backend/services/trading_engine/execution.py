from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .state import PositionState, TradeState
from .utils import parse_numeric

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FillResult:
    code: str
    side: str
    qty: int
    avg_price: float
    reason: str | None = None
    order_id: str | None = None
    raw: dict[str, Any] | None = None



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
) -> FillResult | None:
    if code in state.blacklist_today or code in state.open_positions:
        return None

    quote = api.quote(code)
    price_now = parse_numeric(quote.get("price"))
    if price_now is None or price_now <= 0:
        return None

    cash = float(api.cash_available())
    budget = max(0.0, cash * cash_ratio)
    qty = int(budget // price_now)
    if qty < 1:
        return None

    resp = api.place_order(side="BUY", code=code, qty=qty, order_type=order_type, price=price)

    filled_qty_num = parse_numeric(resp.get("filled_qty"))
    if filled_qty_num is None:
        filled_qty = qty
    else:
        filled_qty = int(filled_qty_num)

    if filled_qty <= 0:
        logger.warning("enter_position: zero fill for %s", code)
        return None

    avg_price_num = parse_numeric(resp.get("avg_price"))
    avg_price = float(avg_price_num) if avg_price_num is not None else price_now
    order_id = _extract_order_id(resp)

    state.open_positions[code] = PositionState(
        type=position_type,
        entry_time=now.isoformat(timespec="seconds"),
        entry_price=float(avg_price),
        qty=filled_qty,
        highest_price=float(avg_price),
        entry_date=asof_date,
        bars_held=0,
    )
    state.blacklist_today.add(code)

    if position_type == "S":
        state.swing_entries_today += 1
        state.swing_entries_week += 1
    else:
        state.day_entries_today += 1

    return FillResult(
        code=code,
        side="BUY",
        qty=filled_qty,
        avg_price=float(avg_price),
        order_id=order_id,
        raw=resp,
    )


def exit_position(
    api: TradingAPI,
    state: TradeState,
    *,
    code: str,
    reason: str,
    now: datetime,
    order_type: str = "MKT",
    price: int | None = None,
) -> FillResult | None:
    pos = state.open_positions.get(code)
    if not pos:
        return None

    resp = api.place_order(side="SELL", code=code, qty=pos.qty, order_type=order_type, price=price)
    quote = api.quote(code)
    market_price = parse_numeric(quote.get("price")) or pos.entry_price

    filled_qty_num = parse_numeric(resp.get("filled_qty"))
    if filled_qty_num is None:
        filled_qty = pos.qty
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
    if pnl < 0:
        state.consecutive_losses_today += 1
    else:
        state.consecutive_losses_today = 0

    state.open_positions.pop(code, None)

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
    max_retry: int = 0,
) -> dict[str, int]:
    del timeout_sec  # open_orders schema is broker-specific; best-effort conservative handling.

    cancelled = 0
    retried = 0
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

        if max_retry > 0:
            side = str(order.get("side") or order.get("sll_buy_dvsn_cd") or "").upper()
            code = str(order.get("code") or order.get("pdno") or "")
            qty = int(parse_numeric(order.get("qty")) or 0)
            if side in {"BUY", "SELL"} and code and qty > 0:
                try:
                    api.place_order(side=side, code=code, qty=qty, order_type="MKT", price=None)
                    retried += 1
                except Exception as exc:
                    logger.warning("retry place_order failed code=%s error=%s", code, exc)

    return {"cancelled": cancelled, "retried": retried}


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
