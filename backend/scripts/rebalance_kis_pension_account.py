from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

from backend.integrations.kis.trading_adapter import KISDirectCredentials, create_trading_api
from backend.services.pension_rebalancing import (
    calculate_equity_trend_metrics,
    PensionAsset,
    PensionHolding,
    PensionOrderPlan,
    QuarterlyMarketSignal,
    build_pension_cash_sweep_plan,
    build_pension_rebalance_plan,
    normalize_regime,
    pct_return,
    quarter_start,
    resolve_quarterly_market_signal,
)
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.execution_support import (
    krx_tick_size,
    next_buy_retry_price,
    normalize_buy_limit_price,
)


DEFAULT_RUNTIME_ENV = Path("/app/runtime/myasset.secrets.env")
DEFAULT_PROD_URL = "https://openapi.koreainvestment.com:9443"
DEFAULT_US_SHORT_BOND_CODE = "0048J0"


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _to_int(value: Any) -> int:
    try:
        return int(float(str(value or "0").replace(",", "").strip() or "0"))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").strip() or "0")
    except (TypeError, ValueError):
        return 0.0


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _aggressive_limit_price(*, side: str, price: int) -> int:
    if side == "BUY":
        return next_buy_retry_price(int(price))
    normalized = normalize_buy_limit_price(int(price))
    tick_size = krx_tick_size(float(normalized))
    return max(tick_size, normalized - tick_size)


class PensionKISClient:
    def __init__(self, env: dict[str, str]) -> None:
        app_key = str(env.get("KIS_MY_APP2") or "").strip()
        app_secret = str(env.get("KIS_MY_SEC2") or "").strip()
        account = str(env.get("KIS_MY_ACCT_STOCK2") or "").strip()
        product = str(env.get("KIS_MY_PROD2") or "").strip() or "01"
        base_url = str(env.get("KIS_PROD") or DEFAULT_PROD_URL).strip()

        missing = [
            name
            for name, value in (
                ("KIS_MY_APP2", app_key),
                ("KIS_MY_SEC2", app_secret),
                ("KIS_MY_ACCT_STOCK2", account),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"missing pension KIS env: {','.join(missing)}")
        self.api = create_trading_api(
            KISDirectCredentials(
                app_key=app_key,
                app_secret=app_secret,
                account=account,
                product=product,
                base_url=base_url,
                token_slot=2,
            )
        )

    def balance(self) -> tuple[list[PensionHolding], int]:
        holdings: list[PensionHolding] = []
        for row in self.api.positions():
            qty = _to_int(row.get("qty"))
            if qty <= 0:
                continue
            price = _to_int(row.get("current_price"))
            value = qty * price
            holdings.append(
                PensionHolding(
                    code=str(row.get("code") or "").strip(),
                    name=str(row.get("name") or "").strip(),
                    qty=qty,
                    price=price,
                    value=value,
                )
            )
        return holdings, self.api.cash_available()

    def quote(self, code: str) -> dict[str, Any]:
        return self.api.quote(code)

    def buy_order_capacity(self, code: str, *, price: int = 0, order_type: str = "00") -> dict[str, int]:
        return self.api.buy_order_capacity(code=code, price=price, order_type=order_type)

    def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return self.api.chart_prices(code, start_date=start_date, end_date=end_date, period_div_code="D")

    def monthly_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
        return self.api.chart_prices(code, start_date=start_date, end_date=end_date, period_div_code="M")

    def place_order(self, *, side: str, code: str, qty: int, price: int) -> dict[str, Any]:
        result = self.api.place_order(side=side, code=code, qty=qty, order_type="limit", price=price)
        return {
            "success": bool(result.get("success")),
            "code": code,
            "side": side,
            "qty": qty,
            "price": price,
            "order_id": result.get("order_id", ""),
            "msg": result.get("msg", ""),
        }

    def open_orders(self) -> list[dict[str, Any]]:
        return self.api.open_orders()

    def daily_order_fills(self, *, code: str = "", order_id: str = "", side: str = "00") -> list[dict[str, Any]]:
        today = datetime.now().strftime("%Y%m%d")
        return self.api.daily_order_fills(start_date=today, end_date=today, code=code, order_id=order_id, side=side)


def _assets_from_env(env: dict[str, str], *, selected_momentum_code: str | None = None) -> list[PensionAsset]:
    sp500 = str(env.get("PENSION_REBALANCE_SP500_CODE") or "360200").strip()
    kospi = str(env.get("PENSION_REBALANCE_KOSPI_CODE") or "237350").strip()
    nasdaq = str(
        env.get("PENSION_REBALANCE_NASDAQ_CODE")
        or env.get("PENSION_REBALANCE_MOMENTUM_CODE")
        or env.get("PENSION_REBALANCE_US_GROWTH_CODE")
        or "426030"
    ).strip()
    bond = str(env.get("PENSION_REBALANCE_US_BOND_CODE") or DEFAULT_US_SHORT_BOND_CODE).strip()
    parking = str(
        env.get("PENSION_REBALANCE_PARKING_CODE")
        or env.get("TRADING_RISK_OFF_PARKING_CODE")
        or TradeEngineConfig().risk_off_parking_code
        or ""
    ).strip()
    momentum_codes = [
        str(selected_momentum_code or "").strip(),
        kospi,
        nasdaq,
    ]
    assets = [
        PensionAsset(sp500, "sp500", "S&P500"),
    ]
    seen = {sp500}
    for code in momentum_codes:
        if code and code not in seen:
            assets.append(PensionAsset(code, "momentum", "Momentum ETF"))
            seen.add(code)
    if bond:
        assets.append(PensionAsset(bond, "bond", "US Short Bond"))
        seen.add(bond)
    if parking and parking not in seen:
        assets.append(PensionAsset(parking, "parking", "Parking ETF"))
    return assets


def _quarterly_return(client: PensionKISClient, code: str, *, today: date) -> float:
    start = quarter_start(today).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    prices = client.daily_prices(code, start_date=start, end_date=end)
    if len(prices) >= 2:
        return pct_return(float(prices[0][1]), float(prices[-1][1]))
    if len(prices) == 1:
        quote = client.quote(code)
        current_price = int(quote.get("price") or prices[-1][1])
        return pct_return(float(prices[0][1]), float(current_price))
    return 0.0


def _trend_start(today: date) -> str:
    return (today - timedelta(days=540)).strftime("%Y%m%d")


def _resolve_quarterly_signal(
    client: PensionKISClient,
    env: dict[str, str],
    requested: str,
) -> QuarterlyMarketSignal:
    sp500_code = str(env.get("PENSION_REBALANCE_SP500_CODE") or "360200").strip()
    kospi_code = str(env.get("PENSION_REBALANCE_KOSPI_CODE") or "237350").strip()
    nasdaq_code = str(
        env.get("PENSION_REBALANCE_NASDAQ_CODE")
        or env.get("PENSION_REBALANCE_MOMENTUM_CODE")
        or env.get("PENSION_REBALANCE_US_GROWTH_CODE")
        or "426030"
    ).strip()
    today = date.today()
    reference_return = _quarterly_return(client, sp500_code, today=today)
    kospi_return = _quarterly_return(client, kospi_code, today=today)
    nasdaq_return = _quarterly_return(client, nasdaq_code, today=today)
    trend_start = _trend_start(today)
    trend_end = today.strftime("%Y%m%d")
    trend_metrics = calculate_equity_trend_metrics(
        daily_prices=client.daily_prices(sp500_code, start_date=trend_start, end_date=trend_end),
        monthly_prices=client.monthly_prices(sp500_code, start_date=trend_start, end_date=trend_end),
    )
    signal = resolve_quarterly_market_signal(
        reference_return_pct=reference_return,
        kospi_return_pct=kospi_return,
        nasdaq_return_pct=nasdaq_return,
        kospi_code=kospi_code,
        nasdaq_code=nasdaq_code,
        trend_metrics=trend_metrics,
    )
    if requested != "auto":
        return QuarterlyMarketSignal(
            regime=normalize_regime(requested),
            reference_return_pct=signal.reference_return_pct,
            kospi_return_pct=signal.kospi_return_pct,
            nasdaq_return_pct=signal.nasdaq_return_pct,
            selected_momentum_code=signal.selected_momentum_code,
            current_price=signal.current_price,
            moving_average_10m=signal.moving_average_10m,
            drawdown_from_recent_high_pct=signal.drawdown_from_recent_high_pct,
            three_month_return_pct=signal.three_month_return_pct,
        )
    configured = str(env.get("PENSION_REBALANCE_REGIME") or "").strip()
    if configured:
        return QuarterlyMarketSignal(
            regime=normalize_regime(configured),
            reference_return_pct=signal.reference_return_pct,
            kospi_return_pct=signal.kospi_return_pct,
            nasdaq_return_pct=signal.nasdaq_return_pct,
            selected_momentum_code=signal.selected_momentum_code,
            current_price=signal.current_price,
            moving_average_10m=signal.moving_average_10m,
            drawdown_from_recent_high_pct=signal.drawdown_from_recent_high_pct,
            three_month_return_pct=signal.three_month_return_pct,
        )
    return signal


def _parking_code_from_env(env: dict[str, str]) -> str:
    return str(
        env.get("PENSION_REBALANCE_PARKING_CODE")
        or env.get("TRADING_RISK_OFF_PARKING_CODE")
        or TradeEngineConfig().risk_off_parking_code
        or ""
    ).strip()


def _apply_buy_capacity(
    *,
    client: PensionKISClient,
    orders: list[PensionOrderPlan],
    orderable_cash: int,
) -> list[PensionOrderPlan]:
    remaining_orderable_cash = orderable_cash
    adjusted_orders: list[PensionOrderPlan] = []
    for order in orders:
        if order.side != "BUY":
            adjusted_orders.append(order)
            continue
        limit_price = _aggressive_limit_price(side="BUY", price=order.price)
        capacity = client.buy_order_capacity(order.code, price=limit_price, order_type="00")
        capacity_qty = max(capacity.get("nrcvb_buy_qty", 0), capacity.get("max_buy_qty", 0))
        cash_qty = remaining_orderable_cash // max(1, limit_price)
        qty_candidates = [order.qty, int(cash_qty)]
        if capacity_qty > 0:
            qty_candidates.append(capacity_qty)
        adjusted_qty = min(qty_candidates)
        if adjusted_qty <= 0:
            continue
        adjusted_amount = adjusted_qty * limit_price
        adjusted_orders.append(
            PensionOrderPlan(
                side=order.side,
                code=order.code,
                bucket=order.bucket,
                qty=adjusted_qty,
                price=limit_price,
                amount=adjusted_amount,
                reason=order.reason,
            )
        )
        remaining_orderable_cash = max(0, remaining_orderable_cash - adjusted_amount)
    return adjusted_orders


def _execute_orders(client: PensionKISClient, orders: list[PensionOrderPlan]) -> int:
    for order in orders:
        order_price = _aggressive_limit_price(side=order.side, price=order.price) if order.side == "SELL" else order.price
        result = client.place_order(side=order.side, code=order.code, qty=order.qty, price=order_price)
        print("order_result", result)
        if not result.get("success"):
            return 1
    return 0


def _has_open_order(client: PensionKISClient, *, code: str, order_id: str) -> bool:
    for order in client.open_orders() or []:
        order_code = str(order.get("code") or "").strip()
        current_order_id = str(order.get("order_id") or "").strip()
        remaining_qty = _to_int(order.get("remaining_qty"))
        if remaining_qty <= 0:
            continue
        if order_id and current_order_id == order_id:
            return True
        if code and order_code == code and str(order.get("side") or "").lower() == "sell":
            return True
    return False


def _sell_order_filled(client: PensionKISClient, *, code: str, order_id: str, qty: int) -> bool:
    fills = client.daily_order_fills(code=code, order_id=order_id, side="01")
    filled_qty = sum(_to_int(fill.get("filled_qty")) for fill in fills)
    return filled_qty >= qty


def _wait_for_sell_fills(client: PensionKISClient, sell_results: list[dict[str, Any]]) -> bool:
    timeout_sec = max(0, _env_int("PENSION_REBALANCE_SELL_FILL_TIMEOUT_SEC", 60))
    poll_sec = max(1, _env_int("PENSION_REBALANCE_SELL_FILL_POLL_SEC", 5))
    deadline = time.monotonic() + timeout_sec
    while True:
        pending: list[dict[str, Any]] = []
        for result in sell_results:
            if not result.get("success"):
                return False
            code = str(result.get("code") or "").strip()
            order_id = str(result.get("order_id") or "").strip()
            qty = _to_int(result.get("qty"))
            if not order_id:
                pending.append(result)
                continue
            if _sell_order_filled(client, code=code, order_id=order_id, qty=qty):
                continue
            pending.append(result)

        if not pending:
            return True
        if time.monotonic() >= deadline:
            print("sell_fill_pending", pending)
            return False
        time.sleep(poll_sec)


def _refresh_prices(client: PensionKISClient, holdings: list[PensionHolding], assets: list[PensionAsset]) -> dict[str, int]:
    prices = {holding.code: holding.price for holding in holdings if holding.price > 0}
    for asset in assets:
        if asset.code not in prices:
            prices[asset.code] = int(client.quote(asset.code).get("price") or 0)
    return prices


def _orderable_cash_for_buys(
    *,
    client: PensionKISClient,
    assets: list[PensionAsset],
    prices: dict[str, int],
    cash: int,
) -> int:
    capacity_values = []
    for asset in assets:
        if asset.bucket in {"sp500", "momentum", "bond", "parking"}:
            limit_price = _aggressive_limit_price(side="BUY", price=prices.get(asset.code, 0))
            capacity = client.buy_order_capacity(asset.code, price=limit_price, order_type="00")
            capacity_values.append(
                max(
                    capacity.get("ord_psbl_cash", 0),
                    capacity.get("nrcvb_buy_amt", 0),
                    capacity.get("max_buy_amt", 0),
                )
            )
    positive_capacity_values = [value for value in capacity_values if value > 0]
    orderable_cash = min(cash, max(positive_capacity_values)) if positive_capacity_values else cash
    cash_buffer_pct = max(0.0, min(0.5, _env_float("PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT", 0.10)))
    return int(orderable_cash * (1.0 - cash_buffer_pct))


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute KIS pension-account rebalancing.")
    parser.add_argument("--regime", default="auto", help="auto, rising, falling, neutral")
    parser.add_argument("--execute", action="store_true", help="place limit orders; default is dry-run")
    parser.add_argument("--no-sells", action="store_true", help="only plan buys with available cash")
    parser.add_argument("--min-order-amount", type=int, default=50_000)
    parser.add_argument("--cash-sweep", action="store_true", help="daily cash/parking sweep without quarterly rebalance")
    args = parser.parse_args()

    env = {**_load_env_file(DEFAULT_RUNTIME_ENV), **os.environ}
    client = PensionKISClient(env)
    signal = None if args.cash_sweep else _resolve_quarterly_signal(client, env, args.regime)
    assets = _assets_from_env(env, selected_momentum_code=signal.selected_momentum_code if signal else None)
    holdings, cash = client.balance()

    prices = _refresh_prices(client, holdings, assets)

    orderable_cash = cash
    if args.execute:
        orderable_cash = _orderable_cash_for_buys(client=client, assets=assets, prices=prices, cash=cash)

    lump_sum_threshold = max(0, _env_int("PENSION_CASH_SWEEP_LUMP_SUM_THRESHOLD", 6_000_000))
    if args.cash_sweep and lump_sum_threshold > 0 and orderable_cash >= lump_sum_threshold:
        signal = _resolve_quarterly_signal(client, env, args.regime)
        assets = _assets_from_env(env, selected_momentum_code=signal.selected_momentum_code)
        for asset in assets:
            if asset.code not in prices:
                prices[asset.code] = int(client.quote(asset.code).get("price") or 0)
        plan = build_pension_rebalance_plan(
            holdings=holdings,
            cash=orderable_cash,
            assets=assets,
            prices=prices,
            regime=signal.regime,
            min_order_amount=args.min_order_amount,
            allow_sells=False,
            parking_code=_parking_code_from_env(env),
            gradual_equity_restore_step=max(
                0.0,
                min(0.5, _env_float("PENSION_REBALANCE_EQUITY_RESTORE_STEP_PCT", 0.20)),
            ),
        )
    elif args.cash_sweep:
        plan = build_pension_cash_sweep_plan(
            holdings=holdings,
            cash=orderable_cash,
            assets=assets,
            prices=prices,
            min_order_amount=args.min_order_amount,
            parking_code=_parking_code_from_env(env),
        )
    else:
        assert signal is not None
        plan = build_pension_rebalance_plan(
            holdings=holdings,
            cash=orderable_cash,
            assets=assets,
            prices=prices,
            regime=signal.regime,
            min_order_amount=args.min_order_amount,
            allow_sells=not args.no_sells,
            parking_code=_parking_code_from_env(env),
            gradual_equity_restore_step=max(
                0.0,
                min(0.5, _env_float("PENSION_REBALANCE_EQUITY_RESTORE_STEP_PCT", 0.20)),
            ),
        )

    if args.execute:
        sell_orders = [order for order in plan.orders if order.side == "SELL"]
        if sell_orders:
            sell_results: list[dict[str, Any]] = []
            for order in sell_orders:
                order_price = _aggressive_limit_price(side="SELL", price=order.price)
                result = client.place_order(side=order.side, code=order.code, qty=order.qty, price=order_price)
                print("sell_order_result", result)
                sell_results.append(result)
                if not result.get("success"):
                    return 1
            if not _wait_for_sell_fills(client, sell_results):
                return 1

            holdings, cash = client.balance()
            prices = _refresh_prices(client, holdings, assets)
            orderable_cash = _orderable_cash_for_buys(client=client, assets=assets, prices=prices, cash=cash)

            if args.cash_sweep:
                plan = build_pension_cash_sweep_plan(
                    holdings=holdings,
                    cash=orderable_cash,
                    assets=assets,
                    prices=prices,
                    min_order_amount=args.min_order_amount,
                    parking_code=_parking_code_from_env(env),
                )
            else:
                assert signal is not None
                plan = build_pension_rebalance_plan(
                    holdings=holdings,
                    cash=orderable_cash,
                    assets=assets,
                    prices=prices,
                    regime=signal.regime,
                    min_order_amount=args.min_order_amount,
                    allow_sells=False,
                    parking_code=_parking_code_from_env(env),
                    gradual_equity_restore_step=max(
                        0.0,
                        min(0.5, _env_float("PENSION_REBALANCE_EQUITY_RESTORE_STEP_PCT", 0.20)),
                    ),
                )

        buy_orders = [order for order in plan.orders if order.side == "BUY"]
        plan.orders[:] = _apply_buy_capacity(client=client, orders=buy_orders, orderable_cash=orderable_cash)

    print("mode", "EXECUTE" if args.execute else "DRY_RUN")
    print("job", "CASH_SWEEP" if args.cash_sweep else "REBALANCE")
    print("regime", plan.regime)
    if signal is not None:
        print("quarterly_reference_return_pct", round(signal.reference_return_pct, 2))
        print("quarterly_kospi_return_pct", round(signal.kospi_return_pct, 2))
        print("quarterly_nasdaq_return_pct", round(signal.nasdaq_return_pct, 2))
        print("reference_current_price", signal.current_price)
        print("reference_moving_average_10m", round(signal.moving_average_10m, 2))
        print("reference_drawdown_from_recent_high_pct", round(signal.drawdown_from_recent_high_pct, 2))
        print("reference_three_month_return_pct", round(signal.three_month_return_pct, 2))
        print("selected_momentum_code", signal.selected_momentum_code)
    print("total_value", plan.total_value)
    print("cash", plan.cash)
    if args.execute:
        print("balance_cash_d2", cash)
        print("orderable_cash_used", orderable_cash)
    print("target_weights", plan.target_weights)
    print("current_values", plan.current_values)
    print("estimated_cash_after_orders", plan.estimated_cash_after_orders)
    print("orders")
    for order in plan.orders:
        print(
            f"- {order.side} {order.code} bucket={order.bucket} qty={order.qty} "
            f"price={order.price} amount={order.amount} reason={order.reason}"
        )

    if not args.execute:
        return 0

    return _execute_orders(client, plan.orders)


if __name__ == "__main__":
    raise SystemExit(main())
