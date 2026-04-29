from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from .interfaces import TradingAPI
from .types import OrderPayload
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
    raw: OrderPayload | None = None
    sizing: OrderPayload | None = None


@dataclass(slots=True)
class BuySizingSnapshot:
    cash: float
    price_now: float
    max_qty: int | None = None


@dataclass(slots=True)
class SellSizingSnapshot:
    max_qty: int | None = None


def extract_order_id(payload: OrderPayload | None) -> str | None:
    if not payload:
        return None
    for key in ("order_id", "odno", "id", "ord_no"):
        value = payload.get(key)
        if value:
            return str(value)
    return None


def parse_order_time(order: OrderPayload, *, now: datetime) -> datetime | None:
    raw = str(order.get("order_time") or order.get("ord_tmd") or "").strip()
    if not raw:
        return None

    normalized = raw.zfill(6)
    if len(normalized) != 6 or not normalized.isdigit():
        return None

    try:
        hh = int(normalized[0:2])
        mm = int(normalized[2:4])
        ss = int(normalized[4:6])
        return now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
    except ValueError:
        return None


def is_buy_order_side(order: OrderPayload) -> bool:
    side = str(order.get("side") or order.get("sll_buy_dvsn_cd") or "").strip().upper()
    return side in {"BUY", "02"}


def can_retry_buy_with_higher_price(*, order_type: str, price: int | None) -> bool:
    normalized = str(order_type or "").strip().lower()
    return price is not None and price > 0 and normalized in {"limit", "best"}


def next_buy_retry_price(price: int) -> int:
    normalized_price = normalize_buy_limit_price(int(price))
    tick = krx_tick_size(float(normalized_price))
    return int(normalized_price) + tick


def normalize_buy_limit_price(price: int) -> int:
    normalized = int(price)
    tick = krx_tick_size(float(normalized))
    remainder = normalized % tick
    if remainder == 0:
        return normalized
    return normalized + (tick - remainder)


def krx_tick_size(price: float) -> int:
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


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
