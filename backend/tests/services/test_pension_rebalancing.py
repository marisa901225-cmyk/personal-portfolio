from __future__ import annotations

from datetime import date

import pytest

from backend.services.pension_rebalancing import (
    calculate_equity_trend_metrics,
    EquityTrendMetrics,
    PensionAsset,
    PensionHolding,
    build_pension_cash_sweep_plan,
    build_pension_rebalance_plan,
    max_target_weight_drift_pct,
    normalize_regime,
    pct_return,
    quarter_start,
    resolve_quarterly_market_signal,
    select_momentum_candidate,
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


def test_target_weight_drift_uses_total_account_value_including_cash() -> None:
    drift_pct = max_target_weight_drift_pct(
        holdings=[
            PensionHolding("360200", "ACE 미국S&P500", 40, 10_000, 400_000),
            PensionHolding("426030", "TIME 미국나스닥100액티브", 40, 10_000, 400_000),
        ],
        cash=200_000,
        assets=ASSETS,
        target_weights={"sp500": 0.40, "momentum": 0.60, "bond": 0.0, "other": 0.0},
    )

    assert drift_pct == 20.0


def test_target_weight_drift_is_zero_for_empty_account() -> None:
    assert (
        max_target_weight_drift_pct(
            holdings=[],
            cash=0,
            assets=ASSETS,
            target_weights={"sp500": 0.40, "momentum": 0.60, "bond": 0.0, "other": 0.0},
        )
        == 0.0
    )


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


def test_broken_momentum_trend_sells_one_third_and_keeps_proceeds_as_cash() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[
            PensionHolding("360200", "ACE 미국S&P500", 40, 10_000, 400_000),
            PensionHolding("237350", "KODEX 코스피100", 60, 10_000, 600_000),
        ],
        cash=0,
        assets=[
            PensionAsset("360200", "sp500", "ACE 미국S&P500"),
            PensionAsset("237350", "momentum", "KODEX 코스피100", buyable=False, trend_exit=True),
            PensionAsset("241180", "momentum", "TIGER 일본니케이225"),
        ],
        prices={"360200": 10_000, "237350": 10_000, "241180": 10_000},
        regime="rising",
        min_order_amount=10_000,
        trend_exit_step_pct=1.0 / 3.0,
        deploy_leftover_to=None,
    )

    assert [(order.side, order.code, order.qty) for order in plan.orders] == [("SELL", "237350", 20)]
    assert plan.estimated_cash_after_orders == 200_000


def test_reserved_trend_exit_cash_is_not_reinvested_after_sell_fill() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[
            PensionHolding("360200", "ACE 미국S&P500", 40, 10_000, 400_000),
            PensionHolding("237350", "KODEX 코스피100", 40, 10_000, 400_000),
        ],
        cash=200_000,
        assets=[
            PensionAsset("360200", "sp500", "ACE 미국S&P500"),
            PensionAsset("237350", "momentum", "KODEX 코스피100", buyable=False, trend_exit=True),
            PensionAsset("241180", "momentum", "TIGER 일본니케이225"),
        ],
        prices={"360200": 10_000, "237350": 10_000, "241180": 10_000},
        regime="rising",
        min_order_amount=10_000,
        allow_sells=False,
        reserved_cash_amount=200_000,
        deploy_leftover_to=None,
    )

    assert plan.orders == []
    assert plan.estimated_cash_after_orders == 200_000


def test_recovered_momentum_trend_automatically_rebuys_target_gap() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[
            PensionHolding("360200", "ACE 미국S&P500", 40, 10_000, 400_000),
            PensionHolding("237350", "KODEX 코스피100", 40, 10_000, 400_000),
        ],
        cash=200_000,
        assets=[
            PensionAsset("360200", "sp500", "ACE 미국S&P500"),
            PensionAsset("237350", "momentum", "KODEX 코스피100", buyable=True, trend_exit=False),
        ],
        prices={"360200": 10_000, "237350": 10_000},
        regime="rising",
        min_order_amount=10_000,
        allow_sells=False,
        deploy_leftover_to=None,
    )

    assert [(order.side, order.code, order.qty) for order in plan.orders] == [("BUY", "237350", 20)]
    assert plan.estimated_cash_after_orders == 0


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


def test_disabled_leftover_deployment_keeps_unallocated_cash_out_of_sp500() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[PensionHolding("360200", "ACE 미국S&P500", 70, 10_000, 700_000)],
        cash=300_000,
        assets=[
            PensionAsset("360200", "sp500", "ACE 미국S&P500"),
            PensionAsset("237350", "momentum", "KODEX 코스피100", buyable=False),
            PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브", buyable=False),
        ],
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000},
        regime="rising",
        min_order_amount=10_000,
        allow_sells=False,
        deploy_leftover_to=None,
    )

    assert not any(order.side == "BUY" and order.code == "360200" for order in plan.orders)
    assert plan.estimated_cash_after_orders == 300_000


def test_parking_exit_only_funds_buyable_target_gap() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[
            PensionHolding("360200", "ACE 미국S&P500", 30, 10_000, 300_000),
            PensionHolding("440650", "파킹 ETF", 70, 10_000, 700_000),
        ],
        cash=0,
        assets=[
            PensionAsset("360200", "sp500", "ACE 미국S&P500"),
            PensionAsset("237350", "momentum", "KODEX 코스피100", buyable=False),
            PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브", buyable=False),
            PensionAsset("440650", "parking", "파킹 ETF"),
        ],
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "440650": 10_000},
        regime="rising",
        min_order_amount=10_000,
        allow_sells=True,
        deploy_leftover_to=None,
        parking_code="440650",
    )

    assert [(order.side, order.code, order.qty) for order in plan.orders] == [
        ("SELL", "440650", 10),
        ("BUY", "360200", 10),
    ]


def test_parking_stays_put_when_only_unbuyable_momentum_is_underweight() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[
            PensionHolding("360200", "ACE 미국S&P500", 40, 10_000, 400_000),
            PensionHolding("440650", "파킹 ETF", 60, 10_000, 600_000),
        ],
        cash=0,
        assets=[
            PensionAsset("360200", "sp500", "ACE 미국S&P500"),
            PensionAsset("237350", "momentum", "KODEX 코스피100", buyable=False),
            PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브", buyable=False),
            PensionAsset("440650", "parking", "파킹 ETF"),
        ],
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "440650": 10_000},
        regime="rising",
        min_order_amount=10_000,
        allow_sells=True,
        deploy_leftover_to=None,
        parking_code="440650",
    )

    assert plan.orders == []
    assert plan.estimated_cash_after_orders == 0


def test_plan_rejects_same_code_buy_and_sell_round_trip() -> None:
    with pytest.raises(ValueError, match="same-code buy/sell"):
        build_pension_rebalance_plan(
            holdings=[PensionHolding("0048J0", "미국채권 겸 파킹", 10, 10_000, 100_000)],
            cash=0,
            assets=[
                PensionAsset("360200", "sp500", "ACE 미국S&P500"),
                PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브"),
                PensionAsset("0048J0", "bond", "미국채권"),
            ],
            prices={"360200": 1_000_000, "426030": 1_000_000, "0048J0": 10_000},
            regime="rising",
            min_order_amount=10_000,
            allow_sells=True,
            deploy_leftover_to=None,
            parking_code="0048J0",
        )


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


def test_dividend_cash_buys_only_target_gap_without_forcing_parking_exit() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[PensionHolding("440650", "파킹 ETF", 10, 10_000, 100_000)],
        cash=50_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 30_000, "426030": 100_000, "BOND01": 100_000, "440650": 10_000},
        regime="neutral",
        min_order_amount=50_000,
        parking_code="440650",
    )

    assert not any(order.side == "SELL" for order in plan.orders)
    assert plan.orders[0].side == "BUY"
    assert plan.orders[0].code == "360200"
    assert plan.orders[0].bucket == "sp500"
    assert plan.orders[0].qty == 1
    assert plan.orders[-1].code == "440650"


def test_cash_sweep_buys_sp500_when_cash_can_buy_a_share() -> None:
    plan = build_pension_cash_sweep_plan(
        holdings=[],
        cash=120_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 100_000, "440650": 10_000},
        min_order_amount=50_000,
        parking_code="440650",
    )

    assert len(plan.orders) == 1
    assert plan.orders[0].side == "BUY"
    assert plan.orders[0].code == "360200"
    assert plan.orders[0].bucket == "sp500"


def test_cash_sweep_parks_cash_when_sp500_cannot_be_bought() -> None:
    plan = build_pension_cash_sweep_plan(
        holdings=[],
        cash=80_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 100_000, "440650": 10_000},
        min_order_amount=50_000,
        parking_code="440650",
    )

    assert len(plan.orders) == 1
    assert plan.orders[0].side == "BUY"
    assert plan.orders[0].code == "440650"
    assert plan.orders[0].bucket == "parking"


def test_cash_sweep_parks_one_share_when_cash_is_below_old_minimum() -> None:
    plan = build_pension_cash_sweep_plan(
        holdings=[],
        cash=20_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 100_000, "440650": 15_000},
        min_order_amount=15_000,
        parking_code="440650",
    )

    assert len(plan.orders) == 1
    assert plan.orders[0].side == "BUY"
    assert plan.orders[0].code == "440650"
    assert plan.orders[0].qty == 1
    assert plan.orders[0].bucket == "parking"


def test_cash_sweep_sells_parking_before_sp500_when_combined_cash_is_enough() -> None:
    plan = build_pension_cash_sweep_plan(
        holdings=[PensionHolding("440650", "파킹 ETF", 5, 10_000, 50_000)],
        cash=60_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 100_000, "440650": 10_000},
        min_order_amount=50_000,
        parking_code="440650",
    )

    assert plan.orders[0].side == "SELL"
    assert plan.orders[0].code == "440650"
    assert plan.orders[0].bucket == "parking"
    assert plan.orders[1].side == "BUY"
    assert plan.orders[1].code == "360200"


def test_cash_sweep_keeps_parking_when_exit_still_cannot_buy_sp500() -> None:
    plan = build_pension_cash_sweep_plan(
        holdings=[PensionHolding("440650", "파킹 ETF", 1, 15_000, 15_000)],
        cash=6_000,
        assets=ASSETS_WITH_PARKING,
        prices={"360200": 100_000, "440650": 15_000},
        min_order_amount=15_000,
        parking_code="440650",
    )

    assert plan.orders == []


def test_lump_sum_cash_can_be_distributed_without_selling_existing_holdings() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[PensionHolding("360200", "ACE 미국S&P500", 100, 10_000, 1_000_000)],
        cash=6_000_000,
        assets=ASSETS,
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "BOND01": 10_000},
        regime="falling",
        min_order_amount=50_000,
        allow_sells=False,
    )

    assert not any(order.side == "SELL" for order in plan.orders)
    assert any(order.side == "BUY" and order.bucket == "bond" for order in plan.orders)
    assert any(order.side == "BUY" and order.bucket == "momentum" for order in plan.orders)


def test_normalize_regime_accepts_korean_aliases() -> None:
    assert normalize_regime("상승장") == "rising"
    assert normalize_regime("하락장") == "falling"
    assert normalize_regime("폭락장") == "crash"


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


def test_quarterly_signal_marks_falling_below_10m_ma_with_drawdown_and_weak_3m_return() -> None:
    signal = resolve_quarterly_market_signal(
        reference_return_pct=2.0,
        kospi_return_pct=1.0,
        nasdaq_return_pct=2.0,
        kospi_code="237350",
        nasdaq_code="426030",
        trend_metrics=EquityTrendMetrics(
            current_price=88,
            moving_average_10m=100.0,
            drawdown_from_recent_high_pct=-12.0,
            three_month_return_pct=-1.0,
        ),
    )

    assert signal.regime == "falling"


def test_quarterly_signal_marks_crash_below_10m_ma_with_deep_drawdown() -> None:
    signal = resolve_quarterly_market_signal(
        reference_return_pct=2.0,
        kospi_return_pct=1.0,
        nasdaq_return_pct=2.0,
        kospi_code="237350",
        nasdaq_code="426030",
        trend_metrics=EquityTrendMetrics(
            current_price=78,
            moving_average_10m=100.0,
            drawdown_from_recent_high_pct=-22.0,
            three_month_return_pct=1.0,
        ),
    )

    assert signal.regime == "crash"


def test_crash_market_targets_bond_at_50_and_keeps_sp500_at_40() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[
            PensionHolding("360200", "ACE 미국S&P500", 60, 10_000, 600_000),
            PensionHolding("426030", "TIME 미국나스닥100액티브", 40, 10_000, 400_000),
        ],
        cash=0,
        assets=ASSETS,
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "BOND01": 10_000},
        regime="crash",
        min_order_amount=10_000,
    )

    assert plan.target_weights["sp500"] == 0.40
    assert plan.target_weights["momentum"] == 0.10
    assert plan.target_weights["bond"] == 0.50
    assert any(order.side == "SELL" and order.bucket == "sp500" for order in plan.orders)
    assert any(order.side == "SELL" and order.bucket == "momentum" for order in plan.orders)
    assert any(order.side == "BUY" and order.bucket == "bond" for order in plan.orders)


def test_quarterly_signal_recovers_above_10m_ma_with_positive_3m_return() -> None:
    signal = resolve_quarterly_market_signal(
        reference_return_pct=-1.0,
        kospi_return_pct=1.0,
        nasdaq_return_pct=2.0,
        kospi_code="237350",
        nasdaq_code="426030",
        trend_metrics=EquityTrendMetrics(
            current_price=105,
            moving_average_10m=100.0,
            drawdown_from_recent_high_pct=-4.0,
            three_month_return_pct=3.0,
        ),
    )

    assert signal.regime == "rising"


def test_quarterly_signal_stays_neutral_when_3m_return_is_not_recovered() -> None:
    signal = resolve_quarterly_market_signal(
        reference_return_pct=1.0,
        kospi_return_pct=1.0,
        nasdaq_return_pct=2.0,
        kospi_code="237350",
        nasdaq_code="426030",
        trend_metrics=EquityTrendMetrics(
            current_price=105,
            moving_average_10m=100.0,
            drawdown_from_recent_high_pct=-4.0,
            three_month_return_pct=-0.5,
        ),
    )

    assert signal.regime == "neutral"


def test_quarterly_signal_selects_nasdaq_when_it_leads() -> None:
    signal = resolve_quarterly_market_signal(
        reference_return_pct=-0.4,
        kospi_return_pct=1.0,
        nasdaq_return_pct=2.3,
        kospi_code="237350",
        nasdaq_code="426030",
    )

    assert signal.regime == "falling"
    assert signal.selected_momentum_code == "426030"


def test_momentum_candidate_requires_positive_return_and_sp500_outperformance() -> None:
    assert (
        select_momentum_candidate(
            reference_return_pct=4.0,
            kospi_return_pct=5.0,
            nasdaq_return_pct=6.4,
            kospi_code="237350",
            nasdaq_code="426030",
        )
        == ""
    )
    assert (
        select_momentum_candidate(
            reference_return_pct=4.0,
            kospi_return_pct=5.0,
            nasdaq_return_pct=6.5,
            kospi_code="237350",
            nasdaq_code="426030",
        )
        == "426030"
    )
    assert (
        select_momentum_candidate(
            reference_return_pct=-4.0,
            kospi_return_pct=-0.5,
            nasdaq_return_pct=-0.2,
            kospi_code="237350",
            nasdaq_code="426030",
        )
        == ""
    )


def test_no_momentum_candidate_keeps_holdings_classified_but_blocks_new_momentum_buy() -> None:
    plan = build_pension_rebalance_plan(
        holdings=[PensionHolding("426030", "TIME 미국나스닥100액티브", 10, 10_000, 100_000)],
        cash=500_000,
        assets=[
            PensionAsset("360200", "sp500", "ACE 미국S&P500"),
            PensionAsset("237350", "momentum", "KODEX 코스피100", buyable=False),
            PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브", buyable=False),
            PensionAsset("BOND01", "bond", "미국채권"),
        ],
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "BOND01": 10_000},
        regime="rising",
        min_order_amount=10_000,
        allow_sells=False,
    )

    assert plan.current_values["momentum"] == 100_000
    assert not any(order.side == "BUY" and order.bucket == "momentum" for order in plan.orders)
    assert any(order.side == "BUY" and order.bucket == "sp500" for order in plan.orders)


def test_equity_trend_metrics_use_10_month_average_drawdown_and_3m_return() -> None:
    monthly_prices = [(f"2025{month:02d}28", 100 + month) for month in range(1, 11)]
    daily_prices = [
        ("20251001", 120),
        ("20251002", 108),
        ("20251003", 105),
    ]

    metrics = calculate_equity_trend_metrics(daily_prices=daily_prices, monthly_prices=monthly_prices)

    assert metrics.current_price == 105
    assert round(metrics.moving_average_10m, 2) == 105.5
    assert round(metrics.drawdown_from_recent_high_pct, 2) == -12.5
    assert round(metrics.three_month_return_pct, 2) == -1.87


def test_quarter_start_and_pct_return() -> None:
    assert quarter_start(date(2026, 5, 11)) == date(2026, 4, 1)
    assert round(pct_return(100, 112.5), 2) == 12.5


def test_rising_market_restores_equity_weight_gradually() -> None:
    holdings = [
        PensionHolding("360200", "ACE 미국S&P500", 50, 10_000, 500_000),
        PensionHolding("426030", "TIME 미국나스닥100액티브", 20, 10_000, 200_000),
        PensionHolding("BOND01", "미국채권", 30, 10_000, 300_000),
    ]

    plan = build_pension_rebalance_plan(
        holdings=holdings,
        cash=0,
        assets=ASSETS,
        prices={"360200": 10_000, "237350": 10_000, "426030": 10_000, "BOND01": 10_000},
        regime="rising",
        min_order_amount=10_000,
        gradual_equity_restore_step=0.20,
    )

    assert round(plan.target_weights["sp500"], 2) == 0.36
    assert round(plan.target_weights["momentum"], 2) == 0.54
    assert round(plan.target_weights["bond"], 2) == 0.10


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
