from __future__ import annotations

from datetime import date

from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    build_pension_rebalance_plan,
    normalize_regime,
    pct_return,
    quarter_start,
    resolve_quarterly_market_signal,
)


ASSETS = [
    PensionAsset("360200", "sp500", "ACE 미국S&P500"),
    PensionAsset("237350", "momentum", "KODEX 코스피100"),
    PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브"),
    PensionAsset("BOND01", "bond", "미국채권"),
]

ASSETS_WITH_PARKING = [
    *ASSETS,
    PensionAsset("440650", "parking", "파킹 ETF"),
]


def test_rising_market_targets_sp500_at_40_and_momentum_etf_at_60() -> None:
    holdings = [
        PensionHolding("360200", "ACE 미국S&P500", 80, 10_000, 800_000),
        PensionHolding("426030", "TIME 미국나스닥100액티브", 20, 10_000, 200_000),
    ]

    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=0,
        assets=ASSETS,
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "BOND01": 10_000},
        regime="rising",
        min_order_amount=10_000,
    )

    assert plan.target_weights["sp500"] == 0.40
    assert plan.target_weights["momentum"] == 0.60
    assert any(order.side == "SELL" and order.code == "360200" for order in plan.orders)
    assert any(order.side == "BUY" and order.bucket == "momentum" for order in plan.orders)


def test_falling_market_reduces_momentum_etf_and_adds_us_bond() -> None:
    holdings = [
        PensionHolding("360200", "ACE 미국S&P500", 30, 10_000, 300_000),
        PensionHolding("426030", "TIME 미국나스닥100액티브", 70, 10_000, 700_000),
    ]

    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=0,
        assets=ASSETS,
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "BOND01": 10_000},
        regime="falling",
        min_order_amount=10_000,
    )

    assert plan.target_weights["momentum"] == 0.20
    assert plan.target_weights["bond"] == 0.30
    assert any(order.side == "SELL" and order.bucket == "momentum" for order in plan.orders)
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


def test_residual_cash_below_sp500_unit_is_parked() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[],
        cash=80_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 100_000, "426030": 100_000, "BOND01": 100_000, "440650": 10_000},
        regime="neutral",
        min_order_amount=50_000,
        allow_sells=False,
        parking_code="440650",
    )

    assert plan.orders[-1].side == "BUY"
    assert plan.orders[-1].code == "440650"
    assert plan.orders[-1].bucket == "parking"
    assert plan.estimated_cash_after_orders == 0


def test_dividend_cash_trigger_exits_parking_and_buys_sp500() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[PensionHolding("440650", "파킹 ETF", 10, 10_000, 100_000)],
        cash=50_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 30_000, "426030": 100_000, "BOND01": 100_000, "440650": 10_000},
        regime="neutral",
        min_order_amount=50_000,
        parking_code="440650",
    )

    assert plan.orders[0].side == "SELL"
    assert plan.orders[0].code == "440650"
    assert plan.orders[0].bucket == "parking"
    assert plan.orders[1].side == "BUY"
    assert plan.orders[1].code == "360200"
    assert plan.orders[1].bucket == "sp500"


def test_normalize_regime_accepts_korean_aliases() -> None:
    assert normalize_regime("상승장") == "rising"
    assert normalize_regime("하락장") == "falling"


def test_quarterly_signal_uses_reference_return_for_regime_and_kospi_nasdaq_momentum() -> None:
    signal = resolve_quarterly_market_signal(
        reference_return_pct=1.2,
        kospi_return_pct=5.1,
        nasdaq_return_pct=3.2,
        kospi_code="237350",
        nasdaq_code="426030",
    )

    assert signal.regime == "rising"
    assert signal.selected_momentum_code == "237350"


def test_quarterly_signal_selects_nasdaq_when_it_leads() -> None:
    signal = resolve_quarterly_market_signal(
        reference_return_pct=-0.4,
        kospi_return_pct=1.0,
        nasdaq_return_pct=2.0,
        kospi_code="237350",
        nasdaq_code="426030",
    )

    assert signal.regime == "falling"
    assert signal.selected_momentum_code == "426030"


def test_quarter_start_and_pct_return() -> None:
    assert quarter_start(date(2026, 5, 11)) == date(2026, 4, 1)
    assert round(pct_return(100, 112.5), 2) == 12.5


def test_unselected_nasdaq_is_kept_inside_momentum_bucket() -> None:
    holdings = [
        PensionHolding("237350", "KODEX 코스피100", 40, 10_000, 400_000),
        PensionHolding("426030", "TIME 미국나스닥100액티브", 40, 10_000, 400_000),
        PensionHolding("360200", "ACE 미국S&P500", 20, 10_000, 200_000),
    ]

    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=0,
        assets=ASSETS,
        prices={"237350": 10_000, "426030": 10_000, "360200": 10_000, "BOND01": 10_000},
        regime="rising",
        min_order_amount=10_000,
    )

    assert not any(order.side == "SELL" and order.code == "426030" for order in plan.orders)
