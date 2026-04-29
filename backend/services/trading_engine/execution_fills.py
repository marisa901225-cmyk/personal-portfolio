from __future__ import annotations

import logging

from .interfaces import TradingAPI
from .types import OrderPayload
from .utils import parse_numeric

logger = logging.getLogger(__name__)


def get_broker_position_snapshot(
    *,
    api: TradingAPI,
    code: str,
) -> tuple[int, float | None]:
    try:
        for item in api.positions() or []:
            broker_code = str(item.get("code") or item.get("pdno") or "").strip()
            if broker_code != str(code).strip():
                continue
            qty = int(parse_numeric(item.get("qty") or item.get("hldg_qty")) or 0)
            avg_price = parse_numeric(item.get("avg_price") or item.get("pchs_avg_pric"))
            return qty, float(avg_price) if avg_price is not None and avg_price > 0 else None
    except Exception as exc:
        logger.warning("broker position snapshot failed code=%s error=%s", code, exc)
    return 0, None


def resolve_buy_fill(
    *,
    api: TradingAPI,
    code: str,
    fallback_price: float,
    response: OrderPayload,
    broker_before_qty: int,
) -> tuple[int, float | None]:
    broker_after_qty, broker_avg_price = get_broker_position_snapshot(api=api, code=code)
    broker_fill_qty = max(0, broker_after_qty - broker_before_qty)
    if broker_fill_qty > 0 and broker_avg_price is not None and broker_avg_price > 0:
        return broker_fill_qty, float(broker_avg_price)

    response_fill_qty = int(parse_numeric(response.get("filled_qty")) or 0)
    response_avg_price = parse_numeric(response.get("avg_price"))
    if response_fill_qty > 0:
        avg_price = float(response_avg_price) if response_avg_price is not None and response_avg_price > 0 else fallback_price
        return response_fill_qty, avg_price
    return 0, None


def resolve_sell_fill(
    *,
    api: TradingAPI,
    code: str,
    response: OrderPayload,
    broker_before_qty: int,
    requested_qty: int,
    fallback_price: float,
) -> tuple[int, float | None]:
    broker_after_qty, _ = get_broker_position_snapshot(api=api, code=code)
    broker_fill_qty = max(0, broker_before_qty - broker_after_qty)

    avg_price: float | None = None
    if broker_fill_qty > 0 and hasattr(api, "get_today_sell_avg_price"):
        try:
            avg_price = api.get_today_sell_avg_price(code)
        except Exception as exc:
            logger.warning("exit_position: get_today_sell_avg_price failed code=%s err=%s", code, exc)
        if avg_price is not None and avg_price > 0:
            return broker_fill_qty, float(avg_price)

    response_fill_qty = int(parse_numeric(response.get("filled_qty")) or 0)
    response_avg_price = parse_numeric(response.get("avg_price"))
    if response_fill_qty > 0:
        avg_price = float(response_avg_price) if response_avg_price is not None and response_avg_price > 0 else fallback_price
        return min(response_fill_qty, requested_qty), avg_price
    return 0, None
