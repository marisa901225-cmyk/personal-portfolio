from __future__ import annotations

from backend.services.pension_order_execution import build_final_buy_plan
from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    QuarterlyMarketSignal,
)


def test_final_rising_buy_plan_uses_exact_regime_targets() -> None:
    class Client:
        @staticmethod
        def buy_order_capacity(code: str, *, price: int, order_type: str) -> dict[str, int]:
            return {"nrcvb_buy_qty": 1_000, "nrcvb_buy_amt": 100_000_000}

    holdings = [
        PensionHolding("360200", "ACE 미국S&P500", 30, 10_000, 300_000),
        PensionHolding("241180", "TIGER 일본니케이225", 10, 10_000, 100_000),
    ]
    assets = [
        PensionAsset("360200", "sp500", "ACE 미국S&P500"),
        PensionAsset("241180", "momentum", "TIGER 일본니케이225"),
        PensionAsset("0048J0", "bond", "KODEX 미국머니마켓액티브"),
    ]
    signal = QuarterlyMarketSignal(
        regime="rising",
        reference_return_pct=5.0,
        kospi_return_pct=3.0,
        nasdaq_return_pct=4.0,
        selected_momentum_code="241180",
    )

    plan, _ = build_final_buy_plan(
        client=Client(),
        env={"PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT": "0.05"},
        holdings=holdings,
        cash=600_000,
        assets=assets,
        prices={"360200": 10_000, "241180": 10_000, "0048J0": 10_000},
        signal=signal,
        min_order_amount=50_000,
        trend_exit_step_pct=1.0 / 3.0,
        reserved_cash_amount=0,
    )

    assert plan.target_weights == {
        "sp500": 0.40,
        "momentum": 0.60,
        "bond": 0.0,
        "other": 0.0,
    }
    assert plan.total_value == 1_000_000
    assert plan.cash == 600_000
    assert not any(order.bucket == "bond" for order in plan.orders)
