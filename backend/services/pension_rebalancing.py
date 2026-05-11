from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import floor
from typing import Iterable, Literal


Regime = Literal["rising", "falling", "neutral"]
Bucket = Literal["sp500", "momentum", "bond", "parking", "other"]
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


@dataclass(frozen=True)
class QuarterlyMarketSignal:
    regime: Regime
    reference_return_pct: float
    kospi_return_pct: float
    nasdaq_return_pct: float
    selected_momentum_code: str
    current_price: int = 0
    moving_average_10m: float = 0.0
    drawdown_from_recent_high_pct: float = 0.0
    three_month_return_pct: float = 0.0


@dataclass(frozen=True)
class EquityTrendMetrics:
    current_price: int
    moving_average_10m: float
    drawdown_from_recent_high_pct: float
    three_month_return_pct: float


DEFAULT_TARGETS: dict[Regime, dict[Bucket, float]] = {
    "rising": {"sp500": 0.40, "momentum": 0.60, "bond": 0.0, "other": 0.0},
    "falling": {"sp500": 0.50, "momentum": 0.20, "bond": 0.30, "other": 0.0},
    "neutral": {"sp500": 0.60, "momentum": 0.30, "bond": 0.10, "other": 0.0},
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


def quarter_start(value: date) -> date:
    month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, month, 1)


def pct_return(start_price: float, end_price: float) -> float:
    if start_price <= 0:
        return 0.0
    return (end_price - start_price) / start_price * 100.0


def _last_price_by_month(prices: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    by_month: dict[str, tuple[str, int]] = {}
    for trade_date, price in sorted(prices):
        if not trade_date or price <= 0:
            continue
        month_key = trade_date[:6]
        by_month[month_key] = (trade_date, price)
    return [by_month[key] for key in sorted(by_month)]


def calculate_equity_trend_metrics(
    *,
    daily_prices: list[tuple[str, int]],
    monthly_prices: list[tuple[str, int]] | None = None,
) -> EquityTrendMetrics:
    daily = [(trade_date, price) for trade_date, price in sorted(daily_prices) if trade_date and price > 0]
    monthly = [(trade_date, price) for trade_date, price in sorted(monthly_prices or []) if trade_date and price > 0]
    if not daily and not monthly:
        return EquityTrendMetrics(0, 0.0, 0.0, 0.0)

    current_price = (daily or monthly)[-1][1]
    month_end_prices = monthly or _last_price_by_month(daily)
    ma_source = month_end_prices[-10:]
    moving_average_10m = sum(price for _, price in ma_source) / len(ma_source) if ma_source else 0.0

    recent_high = max((price for _, price in (daily or monthly)), default=current_price)
    drawdown = pct_return(float(recent_high), float(current_price)) if recent_high > 0 else 0.0

    if len(month_end_prices) >= 4:
        three_month_start = month_end_prices[-4][1]
    elif len(daily) >= 64:
        three_month_start = daily[-64][1]
    else:
        three_month_start = (daily or monthly)[0][1]
    three_month_return = pct_return(float(three_month_start), float(current_price))

    return EquityTrendMetrics(
        current_price=int(current_price),
        moving_average_10m=float(moving_average_10m),
        drawdown_from_recent_high_pct=float(drawdown),
        three_month_return_pct=float(three_month_return),
    )


def resolve_quarterly_market_signal(
    *,
    reference_return_pct: float,
    kospi_return_pct: float,
    nasdaq_return_pct: float,
    kospi_code: str,
    nasdaq_code: str,
    trend_metrics: EquityTrendMetrics | None = None,
) -> QuarterlyMarketSignal:
    if trend_metrics and trend_metrics.current_price > 0 and trend_metrics.moving_average_10m > 0:
        below_10m = trend_metrics.current_price < trend_metrics.moving_average_10m
        above_10m = trend_metrics.current_price > trend_metrics.moving_average_10m
        drawdown = trend_metrics.drawdown_from_recent_high_pct
        three_month_return = trend_metrics.three_month_return_pct
        if below_10m and drawdown <= -10.0 and (three_month_return < 0.0 or drawdown <= -20.0):
            regime: Regime = "falling"
        elif above_10m and three_month_return > 0.0:
            regime = "rising"
        else:
            regime = "neutral"
    else:
        regime = "rising" if reference_return_pct > 0 else "falling"
    selected_momentum_code = kospi_code if kospi_return_pct > nasdaq_return_pct else nasdaq_code
    return QuarterlyMarketSignal(
        regime=regime,
        reference_return_pct=reference_return_pct,
        kospi_return_pct=kospi_return_pct,
        nasdaq_return_pct=nasdaq_return_pct,
        selected_momentum_code=selected_momentum_code,
        current_price=trend_metrics.current_price if trend_metrics else 0,
        moving_average_10m=trend_metrics.moving_average_10m if trend_metrics else 0.0,
        drawdown_from_recent_high_pct=trend_metrics.drawdown_from_recent_high_pct if trend_metrics else 0.0,
        three_month_return_pct=trend_metrics.three_month_return_pct if trend_metrics else 0.0,
    )


def _with_gradual_equity_restore(
    *,
    base_targets: dict[Bucket, float],
    current_values: dict[Bucket, int],
    total_value: int,
    restore_step: float | None,
) -> dict[Bucket, float]:
    target_weights = dict(base_targets)
    if restore_step is None or restore_step <= 0 or total_value <= 0:
        return target_weights

    base_equity_weight = target_weights.get("sp500", 0.0) + target_weights.get("momentum", 0.0)
    if base_equity_weight <= 0:
        return target_weights

    current_equity_weight = (
        current_values.get("sp500", 0) + current_values.get("momentum", 0)
    ) / total_value
    restored_equity_weight = min(base_equity_weight, max(0.0, current_equity_weight) + restore_step)
    if restored_equity_weight >= base_equity_weight:
        return target_weights

    sp500_share = target_weights.get("sp500", 0.0) / base_equity_weight
    momentum_share = target_weights.get("momentum", 0.0) / base_equity_weight
    target_weights["sp500"] = restored_equity_weight * sp500_share
    target_weights["momentum"] = restored_equity_weight * momentum_share
    target_weights["bond"] = max(0.0, 1.0 - restored_equity_weight)
    return target_weights


def bucket_values(
    holdings: Iterable[PensionHolding],
    assets: Iterable[PensionAsset],
) -> dict[Bucket, int]:
    bucket_by_code = {asset.code: asset.bucket for asset in assets}
    values: dict[Bucket, int] = {"sp500": 0, "momentum": 0, "bond": 0, "parking": 0, "other": 0}
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
    parking_code: str | None = None,
    parking_cash_trigger_amount: int | None = None,
    gradual_equity_restore_step: float | None = None,
) -> PensionRebalancePlan:
    current_values = bucket_values(holdings, assets)
    total_value = max(0, int(cash)) + sum(max(0, h.value) for h in holdings)
    target_weights = _with_gradual_equity_restore(
        base_targets=DEFAULT_TARGETS[regime],
        current_values=current_values,
        total_value=total_value,
        restore_step=gradual_equity_restore_step if regime == "rising" else None,
    )
    if total_value <= 0:
        return PensionRebalancePlan(regime, 0, int(cash), target_weights, current_values, [], int(cash))

    bucket_by_code = {asset.code: asset.bucket for asset in assets}
    code_by_bucket: dict[Bucket, str] = {}
    for asset in assets:
        code_by_bucket.setdefault(asset.bucket, asset.code)

    orders: list[PensionOrderPlan] = []
    estimated_cash = max(0, int(cash))
    parking_code = str(parking_code or "").strip()
    parking_cash_trigger = min_order_amount if parking_cash_trigger_amount is None else max(
        0,
        int(parking_cash_trigger_amount),
    )
    exited_parking = False

    if allow_sells:
        for holding in holdings:
            bucket = bucket_by_code.get(holding.code, "other")
            if bucket == "parking":
                if parking_code and holding.code == parking_code and cash >= parking_cash_trigger:
                    amount = holding.qty * holding.price
                    if holding.qty > 0 and amount > 0:
                        orders.append(
                            PensionOrderPlan(
                                side="SELL",
                                code=holding.code,
                                bucket=bucket,
                                qty=holding.qty,
                                price=holding.price,
                                amount=amount,
                                reason="parking exit for sp500 cash deployment",
                            )
                        )
                        current_values[bucket] = max(0, current_values.get(bucket, 0) - amount)
                        estimated_cash += amount
                        exited_parking = True
                continue
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

    if exited_parking:
        sp500_code = code_by_bucket.get("sp500")
        sp500_price = int(prices.get(sp500_code or "") or 0)
        if sp500_code and sp500_price > 0:
            sp500_budget = estimated_cash
            qty = floor(sp500_budget / sp500_price)
            if qty > 0:
                amount = qty * sp500_price
                orders.append(
                    PensionOrderPlan(
                        side="BUY",
                        code=sp500_code,
                        bucket="sp500",
                        qty=qty,
                        price=sp500_price,
                        amount=amount,
                        reason="deploy parking exit cash to sp500",
                    )
                )
                current_values["sp500"] = current_values.get("sp500", 0) + amount
                estimated_cash -= amount
    else:
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

    parking_price = int(prices.get(parking_code) or 0)
    if (
        parking_code
        and parking_price > 0
        and estimated_cash >= parking_price
        and (leftover_price <= 0 or estimated_cash < leftover_price)
    ):
        qty = floor(estimated_cash / parking_price)
        if qty > 0:
            amount = qty * parking_price
            orders.append(
                PensionOrderPlan(
                    side="BUY",
                    code=parking_code,
                    bucket="parking",
                    qty=qty,
                    price=parking_price,
                    amount=amount,
                    reason="park residual cash",
                )
            )
            current_values["parking"] = current_values.get("parking", 0) + amount
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


def build_pension_cash_sweep_plan(
    *,
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    prices: dict[str, int],
    min_order_amount: int = 50_000,
    parking_code: str | None = None,
) -> PensionRebalancePlan:
    current_values = bucket_values(holdings, assets)
    total_value = max(0, int(cash)) + sum(max(0, h.value) for h in holdings)
    target_weights = {"sp500": 0.0, "momentum": 0.0, "bond": 0.0, "parking": 0.0, "other": 0.0}
    if total_value <= 0:
        return PensionRebalancePlan("neutral", 0, int(cash), target_weights, current_values, [], int(cash))

    code_by_bucket: dict[Bucket, str] = {}
    for asset in assets:
        code_by_bucket.setdefault(asset.bucket, asset.code)

    sp500_code = code_by_bucket.get("sp500")
    parking_code = str(parking_code or code_by_bucket.get("parking") or "").strip()
    sp500_price = int(prices.get(sp500_code or "") or 0)
    parking_price = int(prices.get(parking_code) or 0)
    estimated_cash = max(0, int(cash))
    orders: list[PensionOrderPlan] = []

    parking_holding = next((holding for holding in holdings if holding.code == parking_code), None)
    if parking_holding and sp500_code and sp500_price > 0 and estimated_cash < sp500_price:
        sell_target = max(min_order_amount, sp500_price - estimated_cash)
        sell_qty = min(parking_holding.qty, floor((sell_target + parking_holding.price - 1) / parking_holding.price))
        if sell_qty > 0 and sell_qty * parking_holding.price >= min_order_amount:
            amount = sell_qty * parking_holding.price
            orders.append(
                PensionOrderPlan(
                    side="SELL",
                    code=parking_holding.code,
                    bucket="parking",
                    qty=sell_qty,
                    price=parking_holding.price,
                    amount=amount,
                    reason="cash sweep parking exit for sp500",
                )
            )
            estimated_cash += amount

    if sp500_code and sp500_price > 0 and estimated_cash >= sp500_price:
        qty = floor(estimated_cash / sp500_price)
        if qty > 0 and qty * sp500_price >= min_order_amount:
            amount = qty * sp500_price
            orders.append(
                PensionOrderPlan(
                    side="BUY",
                    code=sp500_code,
                    bucket="sp500",
                    qty=qty,
                    price=sp500_price,
                    amount=amount,
                    reason="cash sweep buy sp500",
                )
            )
            estimated_cash -= amount

    if (
        not any(order.side == "BUY" and order.bucket == "sp500" for order in orders)
        and parking_code
        and parking_price > 0
        and estimated_cash >= max(min_order_amount, parking_price)
    ):
        qty = floor(estimated_cash / parking_price)
        if qty > 0:
            amount = qty * parking_price
            orders.append(
                PensionOrderPlan(
                    side="BUY",
                    code=parking_code,
                    bucket="parking",
                    qty=qty,
                    price=parking_price,
                    amount=amount,
                    reason="cash sweep park residual cash",
                )
            )
            estimated_cash -= amount

    return PensionRebalancePlan(
        regime="neutral",
        total_value=total_value,
        cash=int(cash),
        target_weights=target_weights,
        current_values=current_values,
        orders=orders,
        estimated_cash_after_orders=estimated_cash,
    )
