from __future__ import annotations

from datetime import date, datetime

import backend.scripts.run_pension_rebalance_scheduler as scheduler
from backend.scripts.rebalance_kis_pension_account import (
    _assets_from_env,
    _execute_orders,
    _parking_code_from_env,
    _quarterly_return,
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
from backend.services.pension_rebalancing import PensionOrderPlan


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
