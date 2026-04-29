from __future__ import annotations

import logging

from .execution_types import BuySizingSnapshot, SellSizingSnapshot
from .interfaces import BuyOrderInfoAPI, SellOrderInfoAPI, TradingAPI
from .utils import parse_numeric

logger = logging.getLogger(__name__)


def resolve_buy_sizing(
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
    if should_use_broker_calc_price(order_type=order_type, requested_price=price) and calc_price is not None and calc_price > 0:
        snapshot.price_now = float(calc_price)

    max_qty = parse_numeric(info.get("nrcvb_buy_qty"))
    if max_qty is None or max_qty <= 0:
        max_qty = parse_numeric(info.get("max_buy_qty"))
    if max_qty is not None and max_qty > 0:
        snapshot.max_qty = int(max_qty)

    return snapshot


def resolve_sell_sizing(
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


def resolve_buy_budget_cash(
    *,
    cash: float,
    cash_ratio: float,
    budget_cash_cap: float | None = None,
) -> float:
    ratio_budget = max(0.0, cash * cash_ratio)
    if budget_cash_cap is None or budget_cash_cap <= 0:
        return ratio_budget
    return max(0.0, min(cash, float(budget_cash_cap)))


def calc_buy_qty(
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


def should_use_broker_calc_price(*, order_type: str, requested_price: int | None) -> bool:
    if requested_price is not None and requested_price > 0:
        return True

    normalized = str(order_type or "").strip().lower()
    return normalized in {"market", "mkt", "conditional"}
