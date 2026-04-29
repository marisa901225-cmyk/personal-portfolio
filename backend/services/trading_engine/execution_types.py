from __future__ import annotations

from dataclasses import dataclass

from .types import OrderPayload


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
