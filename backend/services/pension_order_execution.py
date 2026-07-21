from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date
import os
from pathlib import Path
import time
from typing import Any

from backend.services.pension_exit_review import review_pension_sell_orders
from backend.services.pension_order_safety import (
    DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT,
    PensionExecutionJournal,
    aggregate_and_validate_sell_orders,
    apply_buy_capacity,
    assert_no_open_orders,
    orderable_cash_for_buys,
    pension_signal_key,
)
from backend.services.pension_rebalance_context import (
    PensionKISClient,
    load_exit_review_monthly_prices,
    parking_code_from_env,
    refresh_prices,
    to_int,
)
from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    PensionOrderPlan,
    PensionRebalancePlan,
    QuarterlyMarketSignal,
    build_pension_cash_sweep_plan,
    build_pension_rebalance_plan,
    cap_pension_sell_orders,
)
from backend.services.trading_engine.execution_support import (
    krx_tick_size,
    next_buy_retry_price,
    normalize_buy_limit_price,
)


DEFAULT_EXIT_REVIEW_OUTPUT_DIR = Path("/app/backend/storage/pension_rebalance/monthly_review")
DEFAULT_EXECUTION_STATE_PATH = Path("/app/backend/storage/pension_rebalance/execution_state.json")


class PensionSellExecutionFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedPensionExecution:
    plan: PensionRebalancePlan
    holdings: list[PensionHolding]
    balance_cash: int
    orderable_cash: int
    journal: PensionExecutionJournal
    execution_id: str


def env_int(env: dict[str, str] | None, name: str, default: int) -> int:
    source = os.environ if env is None else env
    raw = str(source.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def env_float(env: dict[str, str] | None, name: str, default: float) -> float:
    source = os.environ if env is None else env
    raw = str(source.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def aggressive_limit_price(*, side: str, price: int) -> int:
    if side == "BUY":
        return next_buy_retry_price(int(price))
    normalized = normalize_buy_limit_price(int(price))
    tick_size = krx_tick_size(float(normalized))
    return max(tick_size, normalized - tick_size)


def apply_order_buy_capacity(
    *,
    client: PensionKISClient,
    orders: list[PensionOrderPlan],
    orderable_cash: int,
    holdings: list[PensionHolding] | None = None,
    total_value: int | None = None,
    max_single_asset_weight_pct: float = DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT,
) -> list[PensionOrderPlan]:
    priced_orders: list[PensionOrderPlan] = []
    for order in orders:
        if order.side != "BUY":
            priced_orders.append(order)
            continue
        limit_price = aggressive_limit_price(side="BUY", price=order.price)
        priced_orders.append(replace(order, price=limit_price, amount=order.qty * limit_price))
    return apply_buy_capacity(
        client=client,
        orders=priced_orders,
        orderable_cash=orderable_cash,
        holdings=holdings,
        total_value=total_value,
        max_single_asset_weight_pct=max_single_asset_weight_pct,
    )


def split_order_qty(qty: int, split_count: int) -> list[int]:
    normalized_qty = max(0, int(qty))
    if normalized_qty <= 0:
        return []
    tranche_count = min(normalized_qty, max(1, int(split_count)))
    base_qty, remainder = divmod(normalized_qty, tranche_count)
    return [base_qty + (1 if index < remainder else 0) for index in range(tranche_count)]


def _order_filled(
    client: PensionKISClient,
    *,
    code: str,
    order_id: str,
    qty: int,
    side: str,
) -> bool:
    fills = client.daily_order_fills(code=code, order_id=order_id, side=side)
    return sum(to_int(fill.get("filled_qty")) for fill in fills) >= qty


def wait_for_buy_fill(
    client: PensionKISClient,
    result: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> bool:
    code = str(result.get("code") or "").strip()
    order_id = str(result.get("order_id") or "").strip()
    qty = to_int(result.get("qty"))
    if not order_id or qty <= 0:
        return False
    timeout_sec = max(0, env_int(env, "PENSION_REBALANCE_BUY_FILL_TIMEOUT_SEC", 60))
    poll_sec = max(1, env_int(env, "PENSION_REBALANCE_BUY_FILL_POLL_SEC", 5))
    deadline = time.monotonic() + timeout_sec
    while True:
        if _order_filled(client, code=code, order_id=order_id, qty=qty, side="02"):
            return True
        if time.monotonic() >= deadline:
            print("buy_fill_pending", result)
            return False
        time.sleep(min(poll_sec, max(0.0, deadline - time.monotonic())))


def execute_orders(
    client: PensionKISClient,
    orders: list[PensionOrderPlan],
    *,
    env: dict[str, str] | None = None,
) -> int:
    buy_split_count = max(1, env_int(env, "PENSION_REBALANCE_BUY_SPLIT_COUNT", 3))
    for order in orders:
        split_buy = order.side == "BUY" and order.bucket not in {"bond", "parking"}
        tranche_qtys = split_order_qty(order.qty, buy_split_count) if split_buy else [order.qty]
        for tranche_index, tranche_qty in enumerate(tranche_qtys, start=1):
            order_price = (
                aggressive_limit_price(side=order.side, price=order.price)
                if order.side == "SELL"
                else order.price
            )
            result = client.place_order(
                side=order.side,
                code=order.code,
                qty=tranche_qty,
                price=order_price,
            )
            print(
                "order_result",
                {**result, "tranche_index": tranche_index, "tranche_count": len(tranche_qtys)},
            )
            if not result.get("success"):
                return 1
            if order.side == "BUY" and not wait_for_buy_fill(client, result, env=env):
                order_id = str(result.get("order_id") or "").strip()
                if order_id:
                    client.cancel_order(order_id)
                return 1
    return 0


def wait_for_sell_fills(
    client: PensionKISClient,
    sell_results: list[dict[str, Any]],
    *,
    env: dict[str, str] | None = None,
) -> bool:
    timeout_sec = max(0, env_int(env, "PENSION_REBALANCE_SELL_FILL_TIMEOUT_SEC", 60))
    poll_sec = max(1, env_int(env, "PENSION_REBALANCE_SELL_FILL_POLL_SEC", 5))
    deadline = time.monotonic() + timeout_sec
    while True:
        pending: list[dict[str, Any]] = []
        for result in sell_results:
            if not result.get("success"):
                return False
            code = str(result.get("code") or "").strip()
            order_id = str(result.get("order_id") or "").strip()
            qty = to_int(result.get("qty"))
            if not order_id or not _order_filled(
                client,
                code=code,
                order_id=order_id,
                qty=qty,
                side="01",
            ):
                pending.append(result)
        if not pending:
            return True
        if time.monotonic() >= deadline:
            print("sell_fill_pending", pending)
            for result in pending:
                order_id = str(result.get("order_id") or "").strip()
                if order_id:
                    client.cancel_order(order_id)
            return False
        time.sleep(poll_sec)


def orderable_cash(
    *,
    cash: int,
    env: dict[str, str] | None = None,
) -> int:
    return orderable_cash_for_buys(
        cash=cash,
        cash_buffer_pct=env_float(env, "PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT", 0.10),
    )


def review_and_validate_sell_orders(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    target_weights: dict[str, float],
    plan: PensionRebalancePlan,
    signal: QuarterlyMarketSignal,
    sell_split_count: int,
) -> tuple[list[PensionOrderPlan], list[PensionHolding], int, dict[str, int], dict[str, int]]:
    sell_orders = cap_pension_sell_orders(
        [order for order in plan.orders if order.side == "SELL"],
        holdings=holdings,
        split_count=sell_split_count,
    )
    if sell_orders:
        review = review_pension_sell_orders(
            holdings=holdings,
            cash=cash,
            assets=assets,
            target_weights=target_weights,
            sell_orders=sell_orders,
            regime=signal.regime,
            monthly_prices_by_code=load_exit_review_monthly_prices(client=client, assets=assets),
            output_dir=str(
                Path(
                    env.get("PENSION_REBALANCE_EXIT_REVIEW_OUTPUT_DIR")
                    or DEFAULT_EXIT_REVIEW_OUTPUT_DIR
                )
                / date.today().strftime("%Y%m%d")
            ),
            model=str(
                env.get("PENSION_REBALANCE_EXIT_AI_MODEL")
                or env.get("PENSION_REBALANCE_MOMENTUM_AI_MODEL")
                or "gpt-5.5"
            ).strip(),
            reasoning_effort=str(
                env.get("PENSION_REBALANCE_EXIT_AI_REASONING_EFFORT") or "high"
            ).strip(),
        )
        print(
            "pension_exit_review",
            {
                "approved_codes": review.approved_codes,
                "summary": review.summary,
                "balance_assessment": review.balance_assessment,
                "route": review.route,
                "chart_paths": review.chart_paths,
                "decisions": [asdict(decision) for decision in review.decisions],
            },
        )
        approved = set(review.approved_codes) if review.route in {"paid", "local"} else set()
        sell_orders = [order for order in sell_orders if order.code in approved]

    latest_holdings, latest_cash = client.balance()
    latest_prices = refresh_prices(client, latest_holdings, assets)
    sellable_qty = {
        code: to_int(client.sell_order_capacity(code).get("ord_psbl_qty"))
        for code in {order.code for order in sell_orders}
    }
    safety = aggregate_and_validate_sell_orders(
        orders=sell_orders,
        holdings=latest_holdings,
        split_count=sell_split_count,
        sellable_qty_by_code=sellable_qty,
    )
    return safety.orders, latest_holdings, latest_cash, latest_prices, safety.max_qty_by_code


def submit_and_wait_sell_orders(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    journal: PensionExecutionJournal,
    execution_id: str,
    sell_orders: list[PensionOrderPlan],
) -> bool:
    results: list[dict[str, Any]] = []
    for order in sell_orders:
        journal.mark_sell_submitted(execution_id=execution_id, code=order.code, qty=order.qty)
        result = {
            **client.place_order(
                side=order.side,
                code=order.code,
                qty=order.qty,
                price=aggressive_limit_price(side="SELL", price=order.price),
            ),
            "bucket": order.bucket,
            "reason": order.reason,
        }
        print("sell_order_result", result)
        results.append(result)
        if not result.get("success"):
            journal.mark_failed(
                execution_id=execution_id,
                reason=f"sell order rejected: {order.code}",
            )
            return False
    if wait_for_sell_fills(client, results, env=env):
        journal.mark_sells_filled(execution_id=execution_id)
        return True
    journal.mark_failed(
        execution_id=execution_id,
        reason="sell fill timeout; pending orders cancelled",
    )
    return False


def build_final_buy_plan(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    prices: dict[str, int],
    signal: QuarterlyMarketSignal,
    min_order_amount: int,
    restore_step: float,
    trend_exit_step_pct: float,
    reserved_cash_amount: int,
    job: str = "REBALANCE",
) -> tuple[PensionRebalancePlan, int]:
    buy_cash = orderable_cash(cash=cash, env=env)
    if job == "CASH_SWEEP":
        plan = build_pension_cash_sweep_plan(
            holdings=holdings,
            cash=buy_cash,
            assets=assets,
            prices=prices,
            min_order_amount=min_order_amount,
            parking_code=parking_code_from_env(env),
        )
    else:
        plan = build_pension_rebalance_plan(
            holdings=holdings,
            cash=buy_cash,
            assets=assets,
            prices=prices,
            regime=signal.regime,
            min_order_amount=min_order_amount,
            allow_sells=False,
            deploy_leftover_to=None,
            parking_code=parking_code_from_env(env),
            gradual_equity_restore_step=restore_step,
            trend_exit_step_pct=trend_exit_step_pct,
            reserved_cash_amount=min(reserved_cash_amount, buy_cash),
        )
    account_total_value = cash + sum(holding.value for holding in holdings)
    plan.orders[:] = apply_order_buy_capacity(
        client=client,
        orders=[order for order in plan.orders if order.side == "BUY"],
        orderable_cash=buy_cash,
        holdings=holdings,
        total_value=account_total_value,
        max_single_asset_weight_pct=env_float(
            env,
            "PENSION_REBALANCE_MAX_SINGLE_ASSET_WEIGHT_PCT",
            DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT,
        ),
    )
    return plan, buy_cash


def prepare_pension_execution(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    plan: PensionRebalancePlan,
    target_weights: dict[str, float],
    holdings: list[PensionHolding],
    cash: int,
    assets: list[PensionAsset],
    signal: QuarterlyMarketSignal,
    min_order_amount: int,
    restore_step: float,
    trend_exit_step_pct: float,
    sell_split_count: int,
    job: str,
) -> PreparedPensionExecution:
    sell_orders, holdings, cash, prices, max_sell_qty = review_and_validate_sell_orders(
        client=client,
        env=env,
        holdings=holdings,
        cash=cash,
        assets=assets,
        target_weights=target_weights,
        plan=plan,
        signal=signal,
        sell_split_count=sell_split_count,
    )
    signal_key = pension_signal_key(
        asof_date=date.today().strftime("%Y%m%d"),
        job=job,
        regime=signal.regime,
        selected_momentum_code=signal.selected_momentum_code,
        trend_exit_codes=signal.momentum_trend_exit_codes,
    )
    journal = PensionExecutionJournal(
        Path(env.get("PENSION_REBALANCE_EXECUTION_STATE_PATH") or DEFAULT_EXECUTION_STATE_PATH)
    )
    execution_id, sell_plan_hash = journal.begin(signal_key=signal_key, sell_orders=sell_orders)
    print(
        "sell_execution_plan",
        {
            "execution_id": execution_id,
            "plan_hash": sell_plan_hash,
            "absolute_max_qty_by_code": max_sell_qty,
            "orders": [asdict(order) for order in sell_orders],
        },
    )
    reserved_proceeds = sum(
        order.amount
        for order in sell_orders
        if order.code in set(signal.momentum_trend_exit_codes)
    )
    assert_no_open_orders(client.open_orders())
    try:
        sells_ok = not sell_orders or submit_and_wait_sell_orders(
            client=client,
            env=env,
            journal=journal,
            execution_id=execution_id,
            sell_orders=sell_orders,
        )
    except Exception as exc:
        journal.mark_failed(
            execution_id=execution_id,
            reason=f"sell execution error: {type(exc).__name__}",
        )
        raise
    if not sells_ok:
        raise PensionSellExecutionFailed("pension sell execution failed")
    if sell_orders:
        holdings, cash = client.balance()
        prices = refresh_prices(client, holdings, assets)
    try:
        buy_plan, buy_cash = build_final_buy_plan(
            client=client,
            env=env,
            holdings=holdings,
            cash=cash,
            assets=assets,
            prices=prices,
            signal=signal,
            min_order_amount=min_order_amount,
            restore_step=restore_step,
            trend_exit_step_pct=trend_exit_step_pct,
            reserved_cash_amount=reserved_proceeds,
            job=job,
        )
    except Exception as exc:
        journal.mark_failed(
            execution_id=execution_id,
            reason=f"buy plan error: {type(exc).__name__}",
        )
        raise
    buy_plan_hash = journal.record_buy_plan(
        execution_id=execution_id,
        signal_key=signal_key,
        buy_orders=buy_plan.orders,
    )
    print(
        "buy_execution_plan",
        {
            "execution_id": execution_id,
            "plan_hash": buy_plan_hash,
            "orderable_cash": buy_cash,
            "orders": [asdict(order) for order in buy_plan.orders],
        },
    )
    return PreparedPensionExecution(
        plan=buy_plan,
        holdings=holdings,
        balance_cash=cash,
        orderable_cash=buy_cash,
        journal=journal,
        execution_id=execution_id,
    )


def execute_prepared_buys(
    *,
    client: PensionKISClient,
    env: dict[str, str],
    prepared: PreparedPensionExecution,
) -> int:
    try:
        assert_no_open_orders(client.open_orders())
        result = execute_orders(client, prepared.plan.orders, env=env)
    except Exception as exc:
        prepared.journal.mark_failed(
            execution_id=prepared.execution_id,
            reason=f"buy execution error: {type(exc).__name__}",
        )
        raise
    if result == 0:
        prepared.journal.mark_success(execution_id=prepared.execution_id)
    else:
        prepared.journal.mark_failed(
            execution_id=prepared.execution_id,
            reason="buy execution failed or timed out",
        )
    return result


__all__ = [
    "PensionSellExecutionFailed",
    "PreparedPensionExecution",
    "aggressive_limit_price",
    "apply_order_buy_capacity",
    "build_final_buy_plan",
    "env_float",
    "env_int",
    "execute_orders",
    "execute_prepared_buys",
    "orderable_cash",
    "prepare_pension_execution",
    "review_and_validate_sell_orders",
    "split_order_qty",
    "submit_and_wait_sell_orders",
    "wait_for_buy_fill",
    "wait_for_sell_fills",
]
