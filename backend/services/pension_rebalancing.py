from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import ceil, floor
from typing import Iterable, Literal


Regime = Literal["rising", "falling", "neutral", "crash"]
Bucket = Literal["sp500", "momentum", "bond", "parking", "other"]
Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class PensionAsset:
    code: str
    bucket: Bucket
    name: str = ""
    buyable: bool = True
    trend_exit: bool = False


@dataclass(frozen=True)
class PensionHolding:
    code: str
    name: str
    qty: int
    price: int
    value: int
    avg_price: float = 0.0
    pnl: int = 0
    pnl_rate: float = 0.0


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
    momentum_trend_exit_codes: tuple[str, ...] = ()
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
    "neutral": {"sp500": 0.55, "momentum": 0.25, "bond": 0.20, "other": 0.0},
    "falling": {"sp500": 0.50, "momentum": 0.20, "bond": 0.30, "other": 0.0},
    "crash": {"sp500": 0.40, "momentum": 0.10, "bond": 0.50, "other": 0.0},
}
DEFAULT_MOMENTUM_OUTPERFORMANCE_THRESHOLD_PCT = 2.5


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
        "crash": "crash",
        "panic": "crash",
        "폭락": "crash",
        "폭락장": "crash",
    }
    normalized = aliases.get(raw, raw)
    if normalized not in DEFAULT_TARGETS:
        raise ValueError("regime must be one of rising, falling, neutral, crash")
    return normalized  # type: ignore[return-value]


def quarter_start(value: date) -> date:
    month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, month, 1)


def pct_return(start_price: float, end_price: float) -> float:
    if start_price <= 0:
        return 0.0
    return (end_price - start_price) / start_price * 100.0


def select_momentum_candidate(
    *,
    reference_return_pct: float,
    kospi_return_pct: float,
    nasdaq_return_pct: float,
    kospi_code: str,
    nasdaq_code: str,
    min_outperformance_pct: float = DEFAULT_MOMENTUM_OUTPERFORMANCE_THRESHOLD_PCT,
) -> str:
    if kospi_return_pct > nasdaq_return_pct:
        candidate_code = kospi_code
        candidate_return = kospi_return_pct
    else:
        candidate_code = nasdaq_code
        candidate_return = nasdaq_return_pct

    if candidate_return <= 0.0:
        return ""
    if candidate_return - reference_return_pct < min_outperformance_pct:
        return ""
    return candidate_code


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
    momentum_outperformance_threshold_pct: float = DEFAULT_MOMENTUM_OUTPERFORMANCE_THRESHOLD_PCT,
    trend_metrics: EquityTrendMetrics | None = None,
) -> QuarterlyMarketSignal:
    if trend_metrics and trend_metrics.current_price > 0 and trend_metrics.moving_average_10m > 0:
        below_10m = trend_metrics.current_price < trend_metrics.moving_average_10m
        above_10m = trend_metrics.current_price > trend_metrics.moving_average_10m
        drawdown = trend_metrics.drawdown_from_recent_high_pct
        three_month_return = trend_metrics.three_month_return_pct
        if below_10m and drawdown <= -20.0:
            regime: Regime = "crash"
        elif below_10m and drawdown <= -10.0 and three_month_return < 0.0:
            regime = "falling"
        elif above_10m and three_month_return > 0.0:
            regime = "rising"
        else:
            regime = "neutral"
    else:
        regime = "rising" if reference_return_pct > 0 else "falling"
    selected_momentum_code = select_momentum_candidate(
        reference_return_pct=reference_return_pct,
        kospi_return_pct=kospi_return_pct,
        nasdaq_return_pct=nasdaq_return_pct,
        kospi_code=kospi_code,
        nasdaq_code=nasdaq_code,
        min_outperformance_pct=momentum_outperformance_threshold_pct,
    )
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


def bucket_values(
    holdings: Iterable[PensionHolding],
    assets: Iterable[PensionAsset],
) -> dict[Bucket, int]:
    bucket_by_code = {asset.code: asset.bucket for asset in assets}
    values: dict[Bucket, int] = {"sp500": 0, "momentum": 0, "bond": 0, "parking": 0, "other": 0}
    for holding in holdings:
        values[bucket_by_code.get(holding.code, "other")] += max(0, int(holding.value))
    return values


def max_target_weight_drift_pct(
    *,
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    target_weights: dict[Bucket, float],
) -> float:
    total_value = max(0, int(cash)) + sum(max(0, holding.value) for holding in holdings)
    if total_value <= 0:
        return 0.0

    current_values = bucket_values(holdings, assets)
    tracked_buckets: tuple[Bucket, ...] = ("sp500", "momentum", "bond")
    return round(
        max(
            abs((current_values.get(bucket, 0) / total_value) - target_weights.get(bucket, 0.0))
            for bucket in tracked_buckets
        )
        * 100.0,
        4,
    )


def _validate_no_same_code_round_trip(orders: list[PensionOrderPlan]) -> None:
    buy_codes = {order.code for order in orders if order.side == "BUY"}
    sell_codes = {order.code for order in orders if order.side == "SELL"}
    overlap = sorted(buy_codes & sell_codes)
    if overlap:
        raise ValueError(f"same-code buy/sell round trip is not allowed: {','.join(overlap)}")


def cap_pension_sell_orders(
    orders: list[PensionOrderPlan],
    *,
    holdings: list[PensionHolding],
    split_count: int,
) -> list[PensionOrderPlan]:
    holding_by_code = {holding.code: holding for holding in holdings}
    normalized_split_count = max(2, int(split_count))
    capped: list[PensionOrderPlan] = []
    for order in orders:
        if order.side != "SELL":
            capped.append(order)
            continue
        holding = holding_by_code.get(order.code)
        if holding is None or holding.qty <= 0:
            continue
        split_qty = max(1, ceil(holding.qty / normalized_split_count))
        qty = min(order.qty, holding.qty, split_qty)
        if qty <= 0:
            continue
        capped.append(
            PensionOrderPlan(
                side=order.side,
                code=order.code,
                bucket=order.bucket,
                qty=qty,
                price=order.price,
                amount=qty * order.price,
                reason=order.reason,
            )
        )
    return capped


def build_pension_rebalance_plan(
    *,
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    prices: dict[str, int],
    regime: Regime,
    min_order_amount: int = 50_000,
    allow_sells: bool = True,
    allow_overweight_sells: bool = True,
    deploy_leftover_to: Bucket | None = "sp500",
    parking_code: str | None = None,
    parking_cash_trigger_amount: int | None = None,
    trend_exit_step_pct: float = 1.0 / 3.0,
    reserved_cash_amount: int = 0,
) -> PensionRebalancePlan:
    current_values = bucket_values(holdings, assets)
    total_value = max(0, int(cash)) + sum(max(0, h.value) for h in holdings)
    target_weights = dict(DEFAULT_TARGETS[regime])
    if total_value <= 0:
        return PensionRebalancePlan(regime, 0, int(cash), target_weights, current_values, [], int(cash))

    bucket_by_code = {asset.code: asset.bucket for asset in assets}
    trend_exit_codes = {asset.code for asset in assets if asset.trend_exit}
    code_by_bucket: dict[Bucket, str] = {}
    for asset in assets:
        if asset.buyable:
            code_by_bucket.setdefault(asset.bucket, asset.code)

    orders: list[PensionOrderPlan] = []
    estimated_cash = max(0, int(cash))
    reserved_cash = min(estimated_cash, max(0, int(reserved_cash_amount)))
    parking_code = str(parking_code or "").strip()
    parking_cash_trigger = min_order_amount if parking_cash_trigger_amount is None else max(
        0,
        int(parking_cash_trigger_amount),
    )
    parking_holdings: list[PensionHolding] = []

    if allow_sells:
        for holding in holdings:
            bucket = bucket_by_code.get(holding.code, "other")
            if bucket == "parking":
                parking_holdings.append(holding)
                continue
            if bucket == "other":
                continue
            if holding.code in trend_exit_codes and holding.qty > 0 and holding.price > 0:
                exit_fraction = max(0.0, min(1.0, float(trend_exit_step_pct)))
                qty = min(holding.qty, max(1, ceil(holding.qty * exit_fraction)))
                amount = qty * holding.price
                orders.append(
                    PensionOrderPlan(
                        side="SELL",
                        code=holding.code,
                        bucket=bucket,
                        qty=qty,
                        price=holding.price,
                        amount=amount,
                        reason="momentum weekly trend exit",
                    )
                )
                current_values[bucket] = max(0, current_values.get(bucket, 0) - amount)
                estimated_cash += amount
                reserved_cash += amount
                continue
            if not allow_overweight_sells:
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

    buy_gaps: list[tuple[int, Bucket]] = []
    for bucket, weight in target_weights.items():
        if bucket == "other" or weight <= 0 or bucket not in code_by_bucket:
            continue
        code = code_by_bucket[bucket]
        if int(prices.get(code) or 0) <= 0:
            continue
        target_value = int(total_value * weight)
        gap = target_value - current_values.get(bucket, 0)
        if gap >= min_order_amount:
            buy_gaps.append((gap, bucket))

    spendable_cash = max(0, estimated_cash - reserved_cash)
    funding_shortfall = max(0, sum(gap for gap, _ in buy_gaps) - spendable_cash)
    if funding_shortfall >= parking_cash_trigger:
        for holding in parking_holdings:
            if holding.code != parking_code or holding.qty <= 0 or holding.price <= 0:
                continue
            qty = min(holding.qty, ceil(funding_shortfall / holding.price))
            amount = qty * holding.price
            orders.append(
                PensionOrderPlan(
                    side="SELL",
                    code=holding.code,
                    bucket="parking",
                    qty=qty,
                    price=holding.price,
                    amount=amount,
                    reason="parking exit for target rebalance",
                )
            )
            current_values["parking"] = max(0, current_values.get("parking", 0) - amount)
            estimated_cash += amount
            funding_shortfall = max(0, funding_shortfall - amount)
            if funding_shortfall == 0:
                break

    for gap, bucket in sorted(buy_gaps, reverse=True):
        code = code_by_bucket.get(bucket)
        if not code:
            continue
        price = int(prices.get(code) or 0)
        if price <= 0:
            continue
        spendable_cash = max(0, estimated_cash - reserved_cash)
        budget = min(gap, spendable_cash)
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

    leftover_bucket = deploy_leftover_to
    leftover_code = code_by_bucket.get(leftover_bucket) if leftover_bucket else None
    leftover_price = int(prices.get(leftover_code or "") or 0)
    sold_codes = {order.code for order in orders if order.side == "SELL"}
    if (
        leftover_bucket
        and leftover_code
        and leftover_code not in sold_codes
        and leftover_price > 0
        and max(0, estimated_cash - reserved_cash) >= max(min_order_amount, leftover_price)
    ):
        qty = floor(max(0, estimated_cash - reserved_cash) / leftover_price)
        if qty > 0:
            amount = qty * leftover_price
            orders.append(
                PensionOrderPlan(
                    side="BUY",
                    code=leftover_code,
                    bucket=leftover_bucket,
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
        and max(0, estimated_cash - reserved_cash) >= parking_price
        and (leftover_price <= 0 or max(0, estimated_cash - reserved_cash) < leftover_price)
    ):
        qty = floor(max(0, estimated_cash - reserved_cash) / parking_price)
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

    _validate_no_same_code_round_trip(orders)
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
        if asset.buyable:
            code_by_bucket.setdefault(asset.bucket, asset.code)

    sp500_code = code_by_bucket.get("sp500")
    parking_code = str(parking_code or code_by_bucket.get("parking") or "").strip()
    sp500_price = int(prices.get(sp500_code or "") or 0)
    parking_price = int(prices.get(parking_code) or 0)
    estimated_cash = max(0, int(cash))
    orders: list[PensionOrderPlan] = []

    parking_holding = next((holding for holding in holdings if holding.code == parking_code), None)
    if (
        parking_holding
        and sp500_code
        and sp500_price > 0
        and estimated_cash < sp500_price
        and estimated_cash + parking_holding.value >= sp500_price
    ):
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

    _validate_no_same_code_round_trip(orders)
    return PensionRebalancePlan(
        regime="neutral",
        total_value=total_value,
        cash=int(cash),
        target_weights=target_weights,
        current_values=current_values,
        orders=orders,
        estimated_cash_after_orders=estimated_cash,
    )
