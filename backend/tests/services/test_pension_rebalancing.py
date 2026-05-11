from __future__ import annotations

from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    build_pension_rebalance_plan,
    normalize_regime,
)


ASSETS = [
    PensionAsset("360200", "sp500", "ACE 미국S&P500"),
    PensionAsset("426030", "us_growth", "TIME 미국나스닥100액티브"),
    PensionAsset("BOND01", "bond", "미국채권"),
]


def test_rising_market_targets_sp500_at_40_and_us_growth_etf_at_60() -> None:
    holdings = [
        PensionHolding("360200", "ACE 미국S&P500", 80, 10_000, 800_000),
        PensionHolding("426030", "TIME 미국나스닥100액티브", 20, 10_000, 200_000),
    ]

    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=0,
        assets=ASSETS,
        prices={"360200": 10_000, "426030": 10_000, "0117V0": 10_000, "BOND01": 10_000},
        regime="rising",
        min_order_amount=10_000,
    )

    assert plan.target_weights["sp500"] == 0.40
    assert plan.target_weights["us_growth"] == 0.60
    assert any(order.side == "SELL" and order.code == "360200" for order in plan.orders)
    assert any(order.side == "BUY" and order.bucket == "us_growth" for order in plan.orders)


def test_falling_market_reduces_us_growth_etf_and_adds_us_bond() -> None:
    holdings = [
        PensionHolding("360200", "ACE 미국S&P500", 30, 10_000, 300_000),
        PensionHolding("426030", "TIME 미국나스닥100액티브", 70, 10_000, 700_000),
    ]

    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=0,
        assets=ASSETS,
        prices={"360200": 10_000, "426030": 10_000, "0117V0": 10_000, "BOND01": 10_000},
        regime="falling",
        min_order_amount=10_000,
    )

    assert plan.target_weights["us_growth"] == 0.20
    assert plan.target_weights["bond"] == 0.30
    assert any(order.side == "SELL" and order.bucket == "us_growth" for order in plan.orders)
    assert any(order.side == "BUY" and order.bucket == "bond" for order in plan.orders)


def test_leftover_cash_is_deployed_to_sp500() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[],
        cash=125_000,
        assets=ASSETS,
        prices={"360200": 10_000, "426030": 100_000, "BOND01": 100_000},
        regime="neutral",
        min_order_amount=50_000,
        allow_sells=False,
    )

    assert plan.orders[-1].side == "BUY"
    assert plan.orders[-1].code == "360200"
    assert plan.estimated_cash_after_orders < 10_000


def test_normalize_regime_accepts_korean_aliases() -> None:
    assert normalize_regime("상승장") == "rising"
    assert normalize_regime("하락장") == "falling"
