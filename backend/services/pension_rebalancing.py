from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterable, Literal


Regime = Literal["rising", "falling", "neutral"]
Bucket = Literal["sp500", "us_growth", "bond", "other"]
Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class PensionAsset:
    code: str
    bucket: Bucket
    name: str = ""


@dataclass(frozen=True)
class PensionHolding:
    code: str
    name: str
    qty: int
    price: int
    value: int


@dataclass(frozen=True)
class PensionOrderPlan:
    side: Side
    code: str
    bucket: Bucket
    qty: int
    price: int
    amount: int
    reason: str


@dataclass(frozen=True)
class PensionRebalancePlan:
    regime: Regime
    total_value: int
    cash: int
    target_weights: dict[Bucket, float]
    current_values: dict[Bucket, int]
    orders: list[PensionOrderPlan]
    estimated_cash_after_orders: int


DEFAULT_TARGETS: dict[Regime, dict[Bucket, float]] = {
    "rising": {"sp500": 0.40, "us_growth": 0.60, "bond": 0.0, "other": 0.0},
    "falling": {"sp500": 0.50, "us_growth": 0.20, "bond": 0.30, "other": 0.0},
    "neutral": {"sp500": 0.60, "us_growth": 0.30, "bond": 0.10, "other": 0.0},
}


def normalize_regime(value: str) -> Regime:
    raw = str(value or "").strip().lower()
    aliases = {
        "up": "rising",
        "bull": "rising",
        "risk_on": "rising",
        "risk-on": "rising",
        "상승": "rising",
        "상승장": "rising",
        "down": "falling",
        "bear": "falling",
        "risk_off": "falling",
        "risk-off": "falling",
        "하락": "falling",
        "하락장": "falling",
        "보합": "neutral",
        "neutral": "neutral",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in DEFAULT_TARGETS:
        raise ValueError("regime must be one of rising, falling, neutral")
    return normalized  # type: ignore[return-value]


def bucket_values(
    holdings: Iterable[PensionHolding],
    assets: Iterable[PensionAsset],
) -> dict[Bucket, int]:
    bucket_by_code = {asset.code: asset.bucket for asset in assets}
    values: dict[Bucket, int] = {"sp500": 0, "us_growth": 0, "bond": 0, "other": 0}
    for holding in holdings:
        values[bucket_by_code.get(holding.code, "other")] += max(0, int(holding.value))
    return values


def build_pension_rebalance_plan(
    *,
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    prices: dict[str, int],
    regime: Regime,
    min_order_amount: int = 50_000,
    allow_sells: bool = True,
    deploy_leftover_to: Bucket = "sp500",
) -> PensionRebalancePlan:
    target_weights = DEFAULT_TARGETS[regime]
    current_values = bucket_values(holdings, assets)
    total_value = max(0, int(cash)) + sum(max(0, h.value) for h in holdings)
    if total_value <= 0:
        return PensionRebalancePlan(regime, 0, int(cash), target_weights, current_values, [], int(cash))

    bucket_by_code = {asset.code: asset.bucket for asset in assets}
    code_by_bucket: dict[Bucket, str] = {}
    for asset in assets:
        code_by_bucket.setdefault(asset.bucket, asset.code)

    orders: list[PensionOrderPlan] = []
    estimated_cash = max(0, int(cash))

    if allow_sells:
        for holding in holdings:
            bucket = bucket_by_code.get(holding.code, "other")
            target_value = int(total_value * target_weights.get(bucket, 0.0))
            overweight = current_values.get(bucket, 0) - target_value
            if overweight < min_order_amount or holding.price <= 0:
                continue
            qty = min(holding.qty, floor(overweight / holding.price))
            if qty <= 0:
                continue
            amount = qty * holding.price
            orders.append(
                PensionOrderPlan(
                    side="SELL",
                    code=holding.code,
                    bucket=bucket,
                    qty=qty,
                    price=holding.price,
                    amount=amount,
                    reason=f"{bucket} overweight",
                )
            )
            current_values[bucket] = max(0, current_values.get(bucket, 0) - amount)
            estimated_cash += amount

    buy_gaps: list[tuple[int, Bucket]] = []
    for bucket, weight in target_weights.items():
        if bucket == "other" or weight <= 0:
            continue
        target_value = int(total_value * weight)
        gap = target_value - current_values.get(bucket, 0)
        if gap >= min_order_amount:
            buy_gaps.append((gap, bucket))

    for gap, bucket in sorted(buy_gaps, reverse=True):
        code = code_by_bucket.get(bucket)
        if not code:
            continue
        price = int(prices.get(code) or 0)
        if price <= 0:
            continue
        budget = min(gap, estimated_cash)
        qty = floor(budget / price)
        if qty <= 0:
            continue
        amount = qty * price
        orders.append(
            PensionOrderPlan(
                side="BUY",
                code=code,
                bucket=bucket,
                qty=qty,
                price=price,
                amount=amount,
                reason=f"{bucket} underweight",
            )
        )
        current_values[bucket] = current_values.get(bucket, 0) + amount
        estimated_cash -= amount

    leftover_code = code_by_bucket.get(deploy_leftover_to)
    leftover_price = int(prices.get(leftover_code or "") or 0)
    if leftover_code and leftover_price > 0 and estimated_cash >= max(min_order_amount, leftover_price):
        qty = floor(estimated_cash / leftover_price)
        if qty > 0:
            amount = qty * leftover_price
            orders.append(
                PensionOrderPlan(
                    side="BUY",
                    code=leftover_code,
                    bucket=deploy_leftover_to,
                    qty=qty,
                    price=leftover_price,
                    amount=amount,
                    reason="deploy leftover cash",
                )
            )
            estimated_cash -= amount

    return PensionRebalancePlan(
        regime=regime,
        total_value=total_value,
        cash=int(cash),
        target_weights=target_weights,
        current_values=current_values,
        orders=orders,
        estimated_cash_after_orders=estimated_cash,
    )
