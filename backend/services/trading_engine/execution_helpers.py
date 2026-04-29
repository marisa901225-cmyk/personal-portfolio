from __future__ import annotations

from datetime import datetime

from .types import OrderPayload


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
