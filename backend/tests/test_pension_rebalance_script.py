from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import backend.scripts.run_pension_rebalance_scheduler as scheduler
from backend.scripts.rebalance_kis_pension_account import (
    _analyze_pension_momentum_universe,
    _allow_overweight_sells,
    _assets_from_env,
    _execute_orders,
    _load_exit_review_monthly_prices,
    _orderable_cash_for_buys,
    _parking_code_from_env,
    _quarterly_return,
    _refresh_prices,
    _split_order_qty,
    _wait_for_sell_fills,
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
        "backend.scripts.rebalance_kis_pension_account.load_stock_master_map",
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
        def daily_order_fills(self, *, code: str = "", order_id: str = "", side: str = "00") -> list[dict[str, int]]:
            return [{"filled_qty": 1}]

    assert not _wait_for_sell_fills(
        Client(),
        [{"success": True, "code": "360200", "order_id": "OD123", "qty": 3}],
    )


def test_split_order_qty_balances_tranches_and_handles_small_quantities() -> None:
    assert _split_order_qty(10, 3) == [4, 3, 3]
    assert _split_order_qty(2, 3) == [1, 1]
    assert _split_order_qty(1, 3) == [1]
    assert _split_order_qty(0, 3) == []


def test_execute_orders_splits_buy_and_waits_for_each_fill(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_BUY_SPLIT_COUNT", "3")
    monkeypatch.setenv("PENSION_REBALANCE_BUY_FILL_TIMEOUT_SEC", "0")

    class Client:
        def __init__(self) -> None:
            self.placed_qty: list[int] = []

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
    assert client.placed_qty == [4, 3, 3]


def test_execute_orders_stops_after_unfilled_buy_tranche(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_BUY_SPLIT_COUNT", "3")
    monkeypatch.setenv("PENSION_REBALANCE_BUY_FILL_TIMEOUT_SEC", "0")

    class Client:
        def __init__(self) -> None:
            self.placed_qty: list[int] = []

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
            if order_id == "OD2":
                return []
            return [{"filled_qty": self.placed_qty[int(order_id.removeprefix("OD")) - 1]}]

    client = Client()
    order = PensionOrderPlan("BUY", "426030", "momentum", 10, 50_000, 500_000, "momentum underweight")

    assert _execute_orders(client, [order]) == 1
    assert client.placed_qty == [4, 3]


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


def test_orderable_cash_skips_unbuyable_assets(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT", "0")

    class Client:
        def __init__(self) -> None:
            self.requested_codes: list[str] = []

        def buy_order_capacity(self, code: str, *, price: int, order_type: str) -> dict[str, int]:
            self.requested_codes.append(code)
            return {"ord_psbl_cash": 300_000}

    client = Client()
    orderable_cash = _orderable_cash_for_buys(
        client=client,
        assets=[
            PensionAsset("360200", "sp500", buyable=True),
            PensionAsset("241180", "momentum", buyable=False),
        ],
        prices={"360200": 10_000, "241180": 10_000},
        cash=500_000,
    )

    assert orderable_cash == 300_000
    assert client.requested_codes == ["360200"]


def test_exit_review_monthly_prices_include_equity_holdings_and_sell_candidates() -> None:
    class Client:
        def __init__(self) -> None:
            self.requested_codes: list[str] = []

        def monthly_prices(self, code: str, *, start_date: str, end_date: str) -> list[tuple[str, int]]:
            self.requested_codes.append(code)
            return [("20260630", 10_000)]

    holdings = [
        PensionHolding("360200", "ACE 미국S&P500", 10, 10_000, 100_000),
        PensionHolding("426030", "TIME 미국나스닥100액티브", 10, 20_000, 200_000),
        PensionHolding("0048J0", "KODEX 미국머니마켓액티브", 10, 10_000, 100_000),
    ]
    assets = [
        PensionAsset("360200", "sp500", "ACE 미국S&P500"),
        PensionAsset("426030", "momentum", "TIME 미국나스닥100액티브"),
        PensionAsset("0048J0", "bond", "KODEX 미국머니마켓액티브"),
    ]
    sell_orders = [
        PensionOrderPlan("SELL", "0048J0", "bond", 4, 10_000, 40_000, "bond overweight"),
    ]
    client = Client()

    histories = _load_exit_review_monthly_prices(
        client=client,
        holdings=holdings,
        assets=assets,
        sell_orders=sell_orders,
    )

    assert set(histories) == {"360200", "426030", "0048J0"}
    assert client.requested_codes == ["360200", "426030", "0048J0"]
