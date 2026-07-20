from __future__ import annotations

import argparse
from contextlib import nullcontext
import os
from pathlib import Path

from backend.services.pension_order_execution import (
    PensionSellExecutionFailed,
    PreparedPensionExecution,
    env_int,
    execute_prepared_buys,
    prepare_pension_execution,
)
from backend.services.pension_order_safety import assert_no_open_orders, pension_execution_lock
from backend.services.pension_rebalance_context import (
    PensionKISClient,
    allow_overweight_sells,
    assets_from_env,
    env_float,
    parking_code_from_env,
    refresh_prices,
    resolve_quarterly_signal,
    validate_buyable_assets,
)
from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    PensionRebalancePlan,
    QuarterlyMarketSignal,
    build_pension_rebalance_plan,
    max_target_weight_drift_pct,
)


DEFAULT_RUNTIME_ENV = Path("/app/runtime/myasset.secrets.env")
DEFAULT_EXECUTION_LOCK_PATH = Path("/app/backend/storage/pension_rebalance/execution.lock")


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


def _print_plan_summary(
    *,
    args: argparse.Namespace,
    signal: QuarterlyMarketSignal,
    plan: PensionRebalancePlan,
    balance_cash: int,
    orderable_cash: int,
) -> None:
    print("mode", "EXECUTE" if args.execute else "DRY_RUN")
    print("job", "CASH_SWEEP" if args.cash_sweep else "REBALANCE")
    print("regime", plan.regime)
    print("quarterly_reference_return_pct", round(signal.reference_return_pct, 2))
    print("quarterly_kospi_return_pct", round(signal.kospi_return_pct, 2))
    print("quarterly_nasdaq_return_pct", round(signal.nasdaq_return_pct, 2))
    print("reference_current_price", signal.current_price)
    print("reference_moving_average_10m", round(signal.moving_average_10m, 2))
    print("reference_drawdown_from_recent_high_pct", round(signal.drawdown_from_recent_high_pct, 2))
    print("reference_three_month_return_pct", round(signal.three_month_return_pct, 2))
    print("selected_momentum_code", signal.selected_momentum_code)
    print("momentum_trend_exit_codes", signal.momentum_trend_exit_codes)
    print("total_value", plan.total_value)
    print("cash", plan.cash)
    if args.execute:
        print("balance_cash_d2", balance_cash)
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


def _drift_allows_execution(
    *,
    args: argparse.Namespace,
    env: dict[str, str],
    plan: PensionRebalancePlan,
    signal: QuarterlyMarketSignal,
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
) -> bool:
    if not args.if_drift:
        return True
    threshold = max(
        0.0,
        min(100.0, env_float(env, "PENSION_REBALANCE_DRIFT_THRESHOLD_PCT", 10.0)),
    )
    drift = max_target_weight_drift_pct(
        holdings=holdings,
        cash=cash,
        assets=assets,
        target_weights=plan.target_weights,
    )
    print("drift_threshold_pct", threshold)
    print("max_target_weight_drift_pct", drift)
    trend_exit_codes = set(signal.momentum_trend_exit_codes)
    has_trend_exit = any(
        order.side == "SELL" and order.code in trend_exit_codes for order in plan.orders
    )
    if drift < threshold and not has_trend_exit:
        print("drift_action", "SKIP")
        return False
    if has_trend_exit:
        print("trend_exit_action", "PARTIAL_SELL")
    print("drift_action", "REBALANCE")
    return True


def _run_pension_rebalance(args: argparse.Namespace, env: dict[str, str]) -> int:
    client = PensionKISClient(env)
    if args.execute:
        assert_no_open_orders(client.open_orders())
    signal = resolve_quarterly_signal(client, env, args.regime)
    holdings, cash = client.balance()
    assets = assets_from_env(
        env,
        selected_momentum_code=signal.selected_momentum_code,
        momentum_trend_exit_codes=signal.momentum_trend_exit_codes,
        holdings=holdings,
    )
    assets = validate_buyable_assets(client=client, env=env, assets=assets)
    prices = refresh_prices(client, holdings, assets)
    restore_step = max(
        0.0,
        min(0.5, env_float(env, "PENSION_REBALANCE_EQUITY_RESTORE_STEP_PCT", 0.20)),
    )
    trend_exit_split_count = max(
        1,
        env_int(env, "PENSION_REBALANCE_TREND_EXIT_SPLIT_COUNT", 3),
    )
    overweight_sells = allow_overweight_sells(signal)
    print("overweight_sell_action", "ENABLED" if overweight_sells else "DISABLED_NO_SELECTION")
    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=cash,
        assets=assets,
        prices=prices,
        regime=signal.regime,
        min_order_amount=args.min_order_amount,
        allow_sells=not args.cash_sweep and not args.no_sells,
        allow_overweight_sells=overweight_sells,
        deploy_leftover_to=None,
        parking_code=parking_code_from_env(env),
        gradual_equity_restore_step=restore_step,
        trend_exit_step_pct=1.0 / trend_exit_split_count,
    )
    if not _drift_allows_execution(
        args=args,
        env=env,
        plan=plan,
        signal=signal,
        holdings=holdings,
        cash=cash,
        assets=assets,
    ):
        return 0

    prepared: PreparedPensionExecution | None = None
    if args.execute:
        try:
            prepared = prepare_pension_execution(
                client=client,
                env=env,
                plan=plan,
                target_weights=dict(plan.target_weights),
                holdings=holdings,
                cash=cash,
                assets=assets,
                signal=signal,
                min_order_amount=args.min_order_amount,
                restore_step=restore_step,
                trend_exit_step_pct=1.0 / trend_exit_split_count,
                sell_split_count=max(
                    2,
                    env_int(
                        env,
                        "PENSION_REBALANCE_SELL_SPLIT_COUNT",
                        trend_exit_split_count,
                    ),
                ),
                job="CASH_SWEEP" if args.cash_sweep else "REBALANCE",
            )
        except PensionSellExecutionFailed:
            return 1
        plan = prepared.plan
        holdings = prepared.holdings
        cash = prepared.balance_cash

    _print_plan_summary(
        args=args,
        signal=signal,
        plan=plan,
        balance_cash=cash,
        orderable_cash=prepared.orderable_cash if prepared else cash,
    )
    if prepared is None:
        return 0
    return execute_prepared_buys(client=client, env=env, prepared=prepared)


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute KIS pension-account rebalancing.")
    parser.add_argument("--regime", default="auto", help="auto, rising, falling, neutral, crash")
    parser.add_argument("--execute", action="store_true", help="place limit orders; default is dry-run")
    parser.add_argument("--no-sells", action="store_true", help="only plan buys with available cash")
    parser.add_argument("--min-order-amount", type=int, default=50_000)
    parser.add_argument("--cash-sweep", action="store_true", help="daily cash/parking sweep")
    parser.add_argument("--if-drift", action="store_true", help="rebalance only past drift threshold")
    args = parser.parse_args()
    if args.cash_sweep and args.if_drift:
        parser.error("--cash-sweep and --if-drift cannot be used together")

    env = {**_load_env_file(DEFAULT_RUNTIME_ENV), **os.environ}
    lock_path = Path(
        env.get("PENSION_REBALANCE_EXECUTION_LOCK_PATH") or DEFAULT_EXECUTION_LOCK_PATH
    )
    lock_context = pension_execution_lock(lock_path) if args.execute else nullcontext()
    with lock_context:
        return _run_pension_rebalance(args, env)


if __name__ == "__main__":
    raise SystemExit(main())
