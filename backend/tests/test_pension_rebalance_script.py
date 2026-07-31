from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

import backend.scripts.run_pension_rebalance_scheduler as scheduler
from backend.services.pension_order_execution import (
    apply_order_buy_capacity as _apply_buy_capacity,
    build_final_buy_plan as _build_final_buy_plan,
    execute_orders as _execute_orders,
    orderable_cash as _orderable_cash_for_buys,
    wait_for_sell_fills as _wait_for_sell_fills,
)
from backend.services.pension_rebalance_context import (
    PensionKISClient,
    allow_overweight_sells as _allow_overweight_sells,
    analyze_momentum_universe as _analyze_pension_momentum_universe,
    assets_from_env as _assets_from_env,
    load_exit_review_monthly_prices as _load_exit_review_monthly_prices,
    parking_code_from_env as _parking_code_from_env,
    quarterly_return as _quarterly_return,
    refresh_prices as _refresh_prices,
)
from backend.scripts.run_pension_rebalance_scheduler import (
    _build_command,
    _is_quarter_window,
    _is_scheduled_trading_day,
    _open_day_from_holiday_rows,
    _quarter_key,
    _should_use_drift_guard,
)
from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    PensionOrderPlan,
    QuarterlyMarketSignal,
)
from backend.services.pension_order_safety import (
    PensionExecutionJournal,
    aggregate_and_validate_sell_orders,
    assert_no_open_orders,
    normalized_price_history,
    pension_execution_lock,
    pension_signal_key,
    resolve_pension_product,
    validate_buyable_pension_assets,
)


def test_quarter_window_uses_quarter_end_month_last_seven_days(monkeypatch) -> None:
    monkeypatch.delenv("PENSION_REBALANCE_QUARTER_WINDOW_DAYS", raising=False)

    assert not _is_quarter_window(datetime(2026, 4, 1, 10, 5))
    assert not _is_quarter_window(datetime(2026, 3, 24, 10, 5))
    assert _is_quarter_window(datetime(2026, 3, 25, 10, 5))
    assert _is_quarter_window(datetime(2026, 3, 31, 10, 5))


def test_quarter_window_days_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_QUARTER_WINDOW_DAYS", "3")

    assert not _is_quarter_window(datetime(2026, 6, 27, 10, 5))
    assert _is_quarter_window(datetime(2026, 6, 28, 10, 5))
    assert _is_quarter_window(datetime(2026, 6, 30, 10, 5))


def test_quarter_key_matches_quarter_end_month() -> None:
    assert _quarter_key(datetime(2026, 3, 31, 10, 5)) == "2026Q1"
    assert _quarter_key(datetime(2026, 6, 30, 10, 5)) == "2026Q2"


def test_schedule_uses_drift_guard_outside_quarter_window() -> None:
    now = datetime(2026, 7, 16, 10, 5)

    assert _should_use_drift_guard(now, {"last_success_quarter": "2026Q3"})


def test_schedule_uses_drift_guard_after_quarterly_rebalance_completed() -> None:
    now = datetime(2026, 9, 30, 10, 5)

    assert _should_use_drift_guard(now, {"last_success_quarter": "2026Q3"})


def test_schedule_runs_normal_rebalance_when_quarterly_rebalance_is_due() -> None:
    now = datetime(2026, 9, 30, 10, 5)

    assert not _should_use_drift_guard(now, {"last_success_quarter": "2026Q2"})


def test_build_command_adds_drift_guard_flag() -> None:
    command = _build_command(execute=True, if_drift=True)

    assert "--if-drift" in command
    assert "--execute" in command


def test_scheduled_rebalance_runs_drift_guard_after_quarter_is_completed(monkeypatch, tmp_path) -> None:
    scheduled_at = scheduler.KST.localize(datetime(2026, 7, 16, 10, 5))
    captured: dict[str, object] = {}

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return scheduled_at

    class Result:
        returncode = 0
        stdout = "drift_action REBALANCE"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return Result()

    def fake_write_state(path, state) -> None:
        captured["state"] = dict(state)

    monkeypatch.setenv("PENSION_REBALANCE_EXECUTE", "1")
    monkeypatch.setattr(scheduler, "datetime", FixedDateTime)
    monkeypatch.setattr(scheduler, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(scheduler, "_read_state", lambda path: {"last_success_quarter": "2026Q3"})
    monkeypatch.setattr(scheduler, "_write_state", fake_write_state)
    monkeypatch.setattr(scheduler, "_is_scheduled_trading_day", lambda now: True)
    monkeypatch.setattr(scheduler.subprocess, "run", fake_run)

    assert scheduler._run_rebalance(reason="schedule") == 0
    assert "--if-drift" in captured["command"]
    assert "--execute" in captured["command"]
    assert captured["state"]["last_success_quarter"] == "2026Q3"
    assert captured["state"]["last_reason"] == "drift_schedule"
    assert captured["state"]["last_rebalance_action"] == "EXECUTED"
    assert captured["state"]["last_rebalance_execute"] is True


def test_open_day_from_holiday_rows_uses_kis_open_flag() -> None:
    rows = [
        {"bass_dt": "20260330", "opnd_yn": "Y"},
        {"bass_dt": "20260331", "opnd_yn": "N"},
    ]

    assert _open_day_from_holiday_rows("20260330", rows) is True
    assert _open_day_from_holiday_rows("20260331", rows) is False
    assert _open_day_from_holiday_rows("20260401", rows) is None


def test_scheduled_trading_day_uses_kis_holiday_lookup(monkeypatch) -> None:
    called: list[str] = []

    def fake_query(date_key: str) -> bool:
        called.append(date_key)
        return date_key == "20260330"

    monkeypatch.setattr(scheduler, "_query_kis_trading_day", fake_query)

    assert _is_scheduled_trading_day(datetime(2026, 3, 30, 10, 5))
    assert not _is_scheduled_trading_day(datetime(2026, 3, 31, 10, 5))
    assert called == ["20260330", "20260331"]


def test_scheduled_trading_day_skips_weekend_without_kis_lookup(monkeypatch) -> None:
    def fake_query(date_key: str) -> bool:
        raise AssertionError("weekends should be skipped before KIS lookup")

    monkeypatch.setattr(scheduler, "_query_kis_trading_day", fake_query)

    assert not _is_scheduled_trading_day(datetime(2026, 3, 29, 10, 5))


def test_assets_from_env_deduplicates_bond_and_parking_code() -> None:
    assets = _assets_from_env(
        {
            "PENSION_REBALANCE_SP500_CODE": "360200",
            "PENSION_REBALANCE_KOSPI_CODE": "237350",
            "PENSION_REBALANCE_NASDAQ_CODE": "426030",
            "PENSION_REBALANCE_US_BOND_CODE": "0048J0",
            "PENSION_REBALANCE_PARKING_CODE": "0048J0",
        }
    )

    codes = [asset.code for asset in assets]
    assert codes.count("0048J0") == 1
    assert [asset.bucket for asset in assets if asset.code == "0048J0"] == ["bond"]


def test_parking_code_is_disabled_when_it_matches_bond_code() -> None:
    assert (
        _parking_code_from_env(
            {
                "PENSION_REBALANCE_US_BOND_CODE": "0048J0",
                "PENSION_REBALANCE_PARKING_CODE": "0048J0",
            }
        )
        == ""
    )


def test_assets_from_env_blocks_momentum_buy_without_reviewed_candidate() -> None:
    assets = _assets_from_env(
        {
            "PENSION_REBALANCE_SP500_CODE": "360200",
            "PENSION_REBALANCE_KOSPI_CODE": "237350",
            "PENSION_REBALANCE_NASDAQ_CODE": "426030",
        },
        selected_momentum_code="",
    )

    momentum_assets = [asset for asset in assets if asset.bucket == "momentum"]
    assert {asset.code for asset in momentum_assets} == {"237350", "426030"}
    assert not any(asset.buyable for asset in momentum_assets)


def test_assets_from_env_keeps_held_country_index_in_momentum_bucket() -> None:
    assets = _assets_from_env(
        {
            "PENSION_REBALANCE_SP500_CODE": "360200",
            "PENSION_REBALANCE_KOSPI_CODE": "237350",
            "PENSION_REBALANCE_NASDAQ_CODE": "426030",
        },
        selected_momentum_code="",
        holdings=[
            PensionHolding("241180", "TIGER 일본니케이225", 199, 35_500, 7_064_500),
        ],
    )

    held_asset = next(asset for asset in assets if asset.code == "241180")
    assert held_asset.bucket == "momentum"
    assert not held_asset.buyable
    assert not held_asset.trend_exit


def test_overweight_sells_require_a_rising_market_selection() -> None:
    def signal(*, regime: str, selected_code: str) -> QuarterlyMarketSignal:
        return QuarterlyMarketSignal(
            regime=regime,
            reference_return_pct=0.0,
            kospi_return_pct=0.0,
            nasdaq_return_pct=0.0,
            selected_momentum_code=selected_code,
        )

    assert not _allow_overweight_sells(signal(regime="rising", selected_code=""))
    assert _allow_overweight_sells(signal(regime="rising", selected_code="241180"))
    assert _allow_overweight_sells(signal(regime="falling", selected_code=""))


def test_assets_from_env_marks_selected_momentum_buyable_first() -> None:
    assets = _assets_from_env(
        {
            "PENSION_REBALANCE_SP500_CODE": "360200",
            "PENSION_REBALANCE_KOSPI_CODE": "237350",
            "PENSION_REBALANCE_NASDAQ_CODE": "426030",
        },
        selected_momentum_code="426030",
    )

    momentum_assets = [asset for asset in assets if asset.bucket == "momentum"]
    assert momentum_assets[0].code == "426030"
    assert momentum_assets[0].buyable
    assert not next(asset for asset in momentum_assets if asset.code == "237350").buyable


def test_assets_from_env_marks_broken_country_index_for_partial_exit() -> None:
    assets = _assets_from_env(
        {
            "PENSION_REBALANCE_SP500_CODE": "360200",
            "PENSION_REBALANCE_KOSPI_CODE": "237350",
            "PENSION_REBALANCE_NASDAQ_CODE": "426030",
        },
        selected_momentum_code="241180",
        momentum_trend_exit_codes=("237350", "453870"),
    )

    by_code = {asset.code: asset for asset in assets}
    assert by_code["241180"].buyable
    assert not by_code["241180"].trend_exit
    assert by_code["237350"].trend_exit
    assert by_code["453870"].trend_exit
    assert not by_code["453870"].buyable


def test_pension_parking_code_does_not_inherit_trading_engine_parking_code() -> None:
    env = {"TRADING_RISK_OFF_PARKING_CODE": "477080"}

    assert _parking_code_from_env(env) == ""
    assert "477080" not in {asset.code for asset in _assets_from_env(env)}


def test_pension_momentum_universe_allows_liquid_country_indices_only(monkeypatch) -> None:
    master_rows = [
        SimpleNamespace(code="237350", name="KODEX 코스피100", is_etf=True),
        SimpleNamespace(code="426030", name="TIME 미국나스닥100액티브", is_etf=True),
        SimpleNamespace(code="133690", name="TIGER 미국나스닥100", is_etf=True),
        SimpleNamespace(code="453870", name="TIGER 인도니프티50", is_etf=True),
        SimpleNamespace(code="241180", name="TIGER 일본니케이225", is_etf=True),
        SimpleNamespace(code="245340", name="TIGER 미국다우존스30", is_etf=True),
        SimpleNamespace(code="251350", name="KODEX MSCI선진국", is_etf=True),
        SimpleNamespace(code="409820", name="KODEX 미국나스닥100레버리지(합성 H)", is_etf=True),
        SimpleNamespace(code="229200", name="KODEX 코스닥150", is_etf=True),
        SimpleNamespace(code="379800", name="KODEX 미국S&P500", is_etf=True),
    ]
    monkeypatch.setattr(
        "backend.services.pension_rebalance_context.load_stock_master_map",
        lambda **kwargs: {row.code: row for row in master_rows},
    )

    avg_values = {
        "237350": 8_000_000_000,
        "426030": 6_000_000_000,
        "133690": 100_000_000_000,
        "453870": 7_000_000_000,
        "241180": 4_000_000_000,
    }
    requested_codes: list[str] = []

    class Client:
        @staticmethod
        def daily_history(code: str, *, end_date: str, lookback: int) -> tuple[list[tuple[str, int]], float]:
            requested_codes.append(code)
            start = date(2025, 1, 1)
            prices = [
                ((start + timedelta(days=index)).strftime("%Y%m%d"), 100 + index)
                for index in range(220)
            ]
            return prices, avg_values[code]

        @staticmethod
        def weekly_prices(code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            start = date(2025, 1, 3)
            return [
                ((start + timedelta(days=index * 7)).strftime("%Y%m%d"), 100 + index)
                for index in range(30)
            ]

    candidates = _analyze_pension_momentum_universe(
        Client(),
        {"PENSION_REBALANCE_MOMENTUM_MIN_AVG_VALUE_20D": "5000000000"},
        kospi_code="237350",
        nasdaq_code="426030",
        end_date="20260715",
    )

    assert {candidate.code for candidate in candidates} == {"237350", "426030", "453870"}
    assert set(requested_codes) == set(avg_values)


def test_quarterly_return_uses_quote_when_only_one_daily_price() -> None:
    class Client:
        def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            return [("20260501", 100)]

        def quote(self, code: str) -> dict[str, int]:
            return {"price": 112}

    assert round(_quarterly_return(Client(), "360200", today=date(2026, 5, 11)), 2) == 12.0


def test_quarterly_return_returns_zero_without_prices() -> None:
    class Client:
        def daily_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            return []

        def quote(self, code: str) -> dict[str, int]:
            raise AssertionError("quote should not be called without an anchor price")

    assert _quarterly_return(Client(), "360200", today=date(2026, 5, 11)) == 0.0


def test_wait_for_sell_fills_accepts_filled_daily_order() -> None:
    class Client:
        def daily_order_fills(self, *, code: str = "", order_id: str = "", side: str = "00") -> list[dict[str, int]]:
            assert code == "360200"
            assert order_id == "OD123"
            assert side == "01"
            return [{"filled_qty": 3}]

    assert _wait_for_sell_fills(
        Client(),
        [{"success": True, "code": "360200", "order_id": "OD123", "qty": 3}],
    )


def test_wait_for_sell_fills_rejects_unfilled_daily_order(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_SELL_FILL_TIMEOUT_SEC", "0")

    class Client:
        def __init__(self) -> None:
            self.cancelled: list[str] = []

        def daily_order_fills(self, *, code: str = "", order_id: str = "", side: str = "00") -> list[dict[str, int]]:
            return [{"filled_qty": 1}]

        def cancel_order(self, order_id: str) -> dict[str, object]:
            self.cancelled.append(order_id)
            return {"success": True, "order_id": order_id}

    client = Client()
    assert not _wait_for_sell_fills(
        client,
        [{"success": True, "code": "360200", "order_id": "OD123", "qty": 3}],
    )
    assert client.cancelled == ["OD123"]


def test_execute_orders_submits_prepared_buy_once(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_BUY_FILL_TIMEOUT_SEC", "0")

    class Client:
        def __init__(self) -> None:
            self.placed_qty: list[int] = []
            self.cancelled: list[str] = []

        def place_order(self, *, side: str, code: str, qty: int, price: int) -> dict[str, object]:
            self.placed_qty.append(qty)
            return {
                "success": True,
                "code": code,
                "side": side,
                "qty": qty,
                "order_id": f"OD{len(self.placed_qty)}",
            }

        def daily_order_fills(
            self,
            *,
            code: str = "",
            order_id: str = "",
            side: str = "00",
        ) -> list[dict[str, int]]:
            assert code == "426030"
            assert side == "02"
            index = int(order_id.removeprefix("OD")) - 1
            return [{"filled_qty": self.placed_qty[index]}]

    client = Client()
    order = PensionOrderPlan("BUY", "426030", "momentum", 10, 50_000, 500_000, "momentum underweight")

    assert _execute_orders(client, [order]) == 0
    assert client.placed_qty == [10]


def test_execute_orders_cancels_unfilled_prepared_buy(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_BUY_FILL_TIMEOUT_SEC", "0")

    class Client:
        def __init__(self) -> None:
            self.placed_qty: list[int] = []
            self.cancelled: list[str] = []

        def place_order(self, *, side: str, code: str, qty: int, price: int) -> dict[str, object]:
            self.placed_qty.append(qty)
            return {
                "success": True,
                "code": code,
                "side": side,
                "qty": qty,
                "order_id": f"OD{len(self.placed_qty)}",
            }

        def daily_order_fills(
            self,
            *,
            code: str = "",
            order_id: str = "",
            side: str = "00",
        ) -> list[dict[str, int]]:
            return []

        def cancel_order(self, order_id: str) -> dict[str, object]:
            self.cancelled.append(order_id)
            return {"success": True, "order_id": order_id}

    client = Client()
    order = PensionOrderPlan("BUY", "426030", "momentum", 10, 50_000, 500_000, "momentum underweight")

    assert _execute_orders(client, [order]) == 1
    assert client.placed_qty == [10]
    assert client.cancelled == ["OD1"]


def test_refresh_prices_skips_unbuyable_asset_without_a_holding() -> None:
    class Client:
        def __init__(self) -> None:
            self.quoted_codes: list[str] = []

        def quote(self, code: str) -> dict[str, int]:
            self.quoted_codes.append(code)
            return {"price": 10_000}

    client = Client()
    prices = _refresh_prices(
        client,
        [],
        [
            PensionAsset("360200", "sp500", buyable=True),
            PensionAsset("241180", "momentum", buyable=False),
        ],
    )

    assert prices == {"360200": 10_000}
    assert client.quoted_codes == ["360200"]


def test_orderable_cash_uses_merged_env_and_enforces_minimum_buffer(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT", "0")

    class Client:
        def __init__(self) -> None:
            self.requested_codes: list[str] = []

        def buy_order_capacity(self, code: str, *, price: int, order_type: str) -> dict[str, int]:
            self.requested_codes.append(code)
            return {"ord_psbl_cash": 300_000}

    client = Client()
    orderable_cash = _orderable_cash_for_buys(
        cash=500_000,
        env={"PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT": "0.20"},
    )

    assert orderable_cash == 400_000
    assert client.requested_codes == []

    minimum_buffer_cash = _orderable_cash_for_buys(
        cash=500_000,
        env={"PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT": "0"},
    )
    assert minimum_buffer_cash == 475_000


def test_exit_review_monthly_prices_exclude_cash_like_sell_candidates() -> None:
    class Client:
        def __init__(self) -> None:
            self.requested_codes: list[str] = []

        def monthly_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            self.requested_codes.append(code)
            return [("20260630", 10_000)]

    assets = [
        PensionAsset("360200", "sp500", "ACE 미국S&P500"),
        PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브"),
        PensionAsset("0048J0", "bond", "KODEX 미국머니마켓액티브"),
    ]
    client = Client()

    histories = _load_exit_review_monthly_prices(
        client=client,
        assets=assets,
    )

    assert set(histories) == {"360200", "426030"}
    assert client.requested_codes == ["360200", "426030"]


def test_pension_product_never_falls_back_to_general_account() -> None:
    with pytest.raises(RuntimeError, match="KIS_MY_PROD2"):
        resolve_pension_product(account="12345678", product="")
    with pytest.raises(RuntimeError, match="product 01"):
        resolve_pension_product(account="12345678", product="01")
    with pytest.raises(RuntimeError, match="mismatch"):
        resolve_pension_product(account="1234567829", product="22")

    assert resolve_pension_product(account="1234567829", product="") == "29"


def test_pension_client_refuses_missing_product_before_api_creation(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.services.pension_rebalance_context.create_trading_api",
        lambda credentials: pytest.fail("API must not be created for an ambiguous account"),
    )

    with pytest.raises(RuntimeError, match="KIS_MY_PROD2"):
        PensionKISClient(
            {
                "KIS_MY_APP2": "app",
                "KIS_MY_SEC2": "secret",
                "KIS_MY_ACCT_STOCK2": "12345678",
            }
        )


def test_assets_from_env_rejects_code_shared_by_equity_and_bond() -> None:
    with pytest.raises(ValueError, match="duplicate pension asset code"):
        _assets_from_env(
            {
                "PENSION_REBALANCE_SP500_CODE": "360200",
                "PENSION_REBALANCE_KOSPI_CODE": "237350",
                "PENSION_REBALANCE_NASDAQ_CODE": "426030",
                "PENSION_REBALANCE_US_BOND_CODE": "360200",
            }
        )


def test_price_history_is_sorted_at_adapter_boundary() -> None:
    assert normalized_price_history(
        [("20260720", 120), ("20260401", 100), ("20260601", 110)]
    ) == [
        ("20260401", 100),
        ("20260601", 110),
        ("20260720", 120),
    ]

    class Client:
        @staticmethod
        def daily_prices(code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            return [("20260720", 120), ("20260401", 100)]

        @staticmethod
        def quote(code: str) -> dict[str, int]:
            raise AssertionError("two sorted prices should be sufficient")

    assert _quarterly_return(Client(), "360200", today=date(2026, 7, 20)) == 20.0


def test_buy_capacity_uses_market_query_and_only_non_margin_fields() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int, str]] = []

        def buy_order_capacity(self, code: str, *, price: int, order_type: str) -> dict[str, int]:
            self.calls.append((code, price, order_type))
            return {
                "nrcvb_buy_qty": 3,
                "nrcvb_buy_amt": 25_000,
                "max_buy_qty": 999,
                "max_buy_amt": 9_999_999,
            }

    client = Client()
    adjusted = _apply_buy_capacity(
        client=client,
        orders=[PensionOrderPlan("BUY", "360200", "sp500", 10, 10_000, 100_000, "buy")],
        orderable_cash=100_000,
    )

    assert client.calls == [("360200", 0, "01")]
    assert len(adjusted) == 1
    assert adjusted[0].qty == 2


def test_buy_capacity_failure_is_fail_closed() -> None:
    class Client:
        @staticmethod
        def buy_order_capacity(code: str, *, price: int, order_type: str) -> dict[str, int]:
            return {"max_buy_qty": 100, "max_buy_amt": 1_000_000}

    with pytest.raises(RuntimeError, match="buy capacity unavailable"):
        _apply_buy_capacity(
            client=Client(),
            orders=[PensionOrderPlan("BUY", "360200", "sp500", 10, 10_000, 100_000, "buy")],
            orderable_cash=100_000,
        )


def test_buy_capacity_enforces_single_asset_absolute_weight_cap() -> None:
    class Client:
        @staticmethod
        def buy_order_capacity(code: str, *, price: int, order_type: str) -> dict[str, int]:
            return {"nrcvb_buy_qty": 100, "nrcvb_buy_amt": 1_000_000}

    adjusted = _apply_buy_capacity(
        client=Client(),
        orders=[PensionOrderPlan("BUY", "360200", "sp500", 20, 10_000, 200_000, "buy")],
        orderable_cash=500_000,
        holdings=[PensionHolding("360200", "ACE 미국S&P500", 55, 10_000, 550_000)],
        total_value=1_000_000,
        max_single_asset_weight_pct=0.60,
    )

    assert len(adjusted) == 1
    assert adjusted[0].qty == 4
    assert adjusted[0].amount <= 50_000


def test_sell_safety_aggregates_duplicates_and_rechecks_absolute_cap() -> None:
    holdings = [PensionHolding("360200", "ACE 미국S&P500", 10, 10_000, 100_000)]
    safe = aggregate_and_validate_sell_orders(
        orders=[
            PensionOrderPlan("SELL", "360200", "sp500", 2, 9_900, 19_800, "drift"),
            PensionOrderPlan("SELL", "360200", "sp500", 2, 9_900, 19_800, "trend"),
        ],
        holdings=holdings,
        split_count=3,
    )

    assert [(order.code, order.qty, order.price, order.amount) for order in safe.orders] == [
        ("360200", 4, 10_000, 40_000)
    ]
    assert safe.max_qty_by_code == {"360200": 4}

    with pytest.raises(RuntimeError, match="absolute cap exceeded"):
        aggregate_and_validate_sell_orders(
            orders=[PensionOrderPlan("SELL", "360200", "sp500", 5, 10_000, 50_000, "sell")],
            holdings=holdings,
            split_count=3,
        )
    with pytest.raises(RuntimeError, match="absolute cap exceeded"):
        aggregate_and_validate_sell_orders(
            orders=[PensionOrderPlan("SELL", "360200", "sp500", 3, 10_000, 30_000, "sell")],
            holdings=holdings,
            split_count=3,
            sellable_qty_by_code={"360200": 2},
        )


def test_sell_safety_never_liquidates_one_share_holding() -> None:
    with pytest.raises(RuntimeError, match="fully liquidate"):
        aggregate_and_validate_sell_orders(
            orders=[PensionOrderPlan("SELL", "360200", "sp500", 1, 10_000, 10_000, "sell")],
            holdings=[PensionHolding("360200", "ACE 미국S&P500", 1, 10_000, 10_000)],
            split_count=3,
        )


def test_open_order_guard_blocks_duplicate_execution() -> None:
    with pytest.raises(RuntimeError, match="open pension orders exist"):
        assert_no_open_orders(
            [
                {
                    "order_id": "OD123",
                    "code": "360200",
                    "remaining_qty": 2,
                    "side": "sell",
                }
            ]
        )

    assert_no_open_orders([{"order_id": "OD123", "remaining_qty": 0, "status": "FILLED"}])


def test_buyable_asset_validation_uses_master_name_family_and_liquidity() -> None:
    assets = [PensionAsset("360200", "sp500", "hardcoded")]
    validated = validate_buyable_pension_assets(
        assets=assets,
        master_by_code={
            "360200": SimpleNamespace(code="360200", name="ACE 미국S&P500", is_etf=True)
        },
        avg_value_20d_by_code={"360200": 5_000_000_000},
        min_avg_value_20d=1_000_000_000,
    )

    assert validated[0].name == "ACE 미국S&P500"

    with pytest.raises(RuntimeError, match="not ETF"):
        validate_buyable_pension_assets(
            assets=assets,
            master_by_code={
                "360200": SimpleNamespace(code="360200", name="삼성전자", is_etf=False)
            },
            avg_value_20d_by_code={"360200": 5_000_000_000},
            min_avg_value_20d=1_000_000_000,
        )
    with pytest.raises(RuntimeError, match="unsafe pension ETF"):
        validate_buyable_pension_assets(
            assets=assets,
            master_by_code={
                "360200": SimpleNamespace(
                    code="360200",
                    name="ACE 미국S&P500 커버드콜",
                    is_etf=True,
                )
            },
            avg_value_20d_by_code={"360200": 5_000_000_000},
            min_avg_value_20d=1_000_000_000,
        )
    with pytest.raises(RuntimeError, match="liquidity below minimum"):
        validate_buyable_pension_assets(
            assets=assets,
            master_by_code={
                "360200": SimpleNamespace(code="360200", name="ACE 미국S&P500", is_etf=True)
            },
            avg_value_20d_by_code={"360200": 100_000_000},
            min_avg_value_20d=1_000_000_000,
        )


def test_execution_journal_blocks_repeat_sell_for_same_quarter_signal(tmp_path) -> None:
    state_path = tmp_path / "execution_state.json"
    signal_key = pension_signal_key(
        asof_date="20260720",
        job="REBALANCE",
        regime="falling",
        selected_momentum_code="",
        trend_exit_codes=("426030",),
    )
    sell_order = PensionOrderPlan(
        "SELL",
        "426030",
        "momentum",
        3,
        10_000,
        30_000,
        "trend exit",
    )
    journal = PensionExecutionJournal(state_path)
    execution_id, plan_hash = journal.begin(signal_key=signal_key, sell_orders=[sell_order])
    journal.mark_sell_submitted(execution_id=execution_id, code="426030", qty=3)
    journal.mark_sells_filled(execution_id=execution_id)
    journal.mark_success(execution_id=execution_id)

    assert len(plan_hash) == 64
    saved = journal.state
    assert saved["last_success_execution_id"] == execution_id
    assert saved["signals"][signal_key]["completed_sell_qty_by_code"] == {"426030": 3}

    with pytest.raises(RuntimeError, match="already sold"):
        PensionExecutionJournal(state_path).begin(
            signal_key=signal_key,
            sell_orders=[sell_order],
        )


def test_execution_journal_blocks_second_buy_for_same_code_and_date(tmp_path) -> None:
    state_path = tmp_path / "execution_state.json"
    signal_key = pension_signal_key(
        asof_date="20260721",
        job="REBALANCE",
        regime="rising",
        selected_momentum_code="241180",
        trend_exit_codes=(),
    )
    journal = PensionExecutionJournal(state_path)
    execution_id, _ = journal.begin(signal_key=signal_key, sell_orders=[])

    journal.mark_buy_submitted(
        execution_id=execution_id,
        code="241180",
        qty=10,
        date_key="20260721",
    )

    reloaded = PensionExecutionJournal(state_path)
    assert reloaded.has_buy_submitted_on_date(
        signal_key=signal_key,
        code="241180",
        date_key="20260721",
    )
    assert not reloaded.has_buy_submitted_on_date(
        signal_key=signal_key,
        code="241180",
        date_key="20260722",
    )


def test_execution_lock_rejects_overlapping_process_run(tmp_path) -> None:
    lock_path = tmp_path / "execution.lock"

    with pension_execution_lock(lock_path):
        with pytest.raises(RuntimeError, match="already running"):
            with pension_execution_lock(lock_path):
                pytest.fail("overlapping execution must not enter the lock")


def test_final_buy_plan_is_recomputed_without_rejected_sell_proceeds() -> None:
    class Client:
        @staticmethod
        def buy_order_capacity(code: str, *, price: int, order_type: str) -> dict[str, int]:
            raise AssertionError("no cash means no buy capacity lookup")

    signal = QuarterlyMarketSignal(
        regime="falling",
        reference_return_pct=-5.0,
        kospi_return_pct=-7.0,
        nasdaq_return_pct=-8.0,
        selected_momentum_code="",
    )
    holdings = [PensionHolding("360200", "ACE 미국S&P500", 100, 10_000, 1_000_000)]
    assets = [
        PensionAsset("360200", "sp500", "ACE 미국S&P500"),
        PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브", buyable=False),
        PensionAsset("0048J0", "bond", "KODEX 미국머니마켓액티브"),
    ]

    plan, orderable_cash = _build_final_buy_plan(
        client=Client(),
        env={"PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT": "0.10"},
        holdings=holdings,
        cash=0,
        assets=assets,
        prices={"360200": 10_000, "426030": 10_000, "0048J0": 10_000},
        signal=signal,
        min_order_amount=10_000,
        trend_exit_step_pct=1.0 / 3.0,
        reserved_cash_amount=0,
    )

    assert orderable_cash == 0
    assert plan.orders == []
