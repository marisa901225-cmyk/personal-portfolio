from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

import backend.scripts.rebalance_kis_pension_account as pension_script
import backend.scripts.run_pension_rebalance_scheduler as scheduler
from backend.services.pension_order_execution import build_final_buy_plan, execute_orders
from backend.services.pension_rebalancing import (
    PensionAsset,
    PensionHolding,
    PensionOrderPlan,
    PensionRebalancePlan,
    QuarterlyMarketSignal,
)


@pytest.mark.parametrize("action", ["EXECUTED", "FAILED"])
def test_scheduled_cash_sweep_skips_after_same_day_rebalance_action(
    monkeypatch,
    tmp_path,
    action: str,
) -> None:
    scheduled_at = scheduler.KST.localize(datetime(2026, 7, 21, 10, 15))

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return scheduled_at

    monkeypatch.setenv("PENSION_CASH_SWEEP_EXECUTE", "1")
    monkeypatch.setattr(scheduler, "datetime", FixedDateTime)
    monkeypatch.setattr(scheduler, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(
        scheduler,
        "_read_state",
        lambda path: {
            "last_rebalance_date": "20260721",
            "last_rebalance_action": action,
            "last_rebalance_execute": True,
        },
    )
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("same-day cash sweep must be skipped"),
    )

    assert scheduler._run_cash_sweep(reason="schedule") == 0


def test_scheduled_cash_sweep_runs_after_same_day_rebalance_skip(monkeypatch, tmp_path) -> None:
    scheduled_at = scheduler.KST.localize(datetime(2026, 7, 21, 10, 15))

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return scheduled_at

    class Result:
        returncode = 0
        stdout = "job CASH_SWEEP"
        stderr = ""

    called: list[list[str]] = []

    monkeypatch.setenv("PENSION_CASH_SWEEP_EXECUTE", "1")
    monkeypatch.setattr(scheduler, "datetime", FixedDateTime)
    monkeypatch.setattr(scheduler, "_state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(
        scheduler,
        "_read_state",
        lambda path: {
            "last_rebalance_date": "20260721",
            "last_rebalance_action": "SKIP",
            "last_rebalance_execute": True,
        },
    )
    monkeypatch.setattr(
        scheduler.subprocess,
        "run",
        lambda command, **kwargs: called.append(command) or Result(),
    )

    assert scheduler._run_cash_sweep(reason="schedule") == 0
    assert called and "--cash-sweep" in called[0]


@pytest.mark.parametrize("bucket", ["bond", "parking"])
def test_execute_orders_does_not_split_cash_like_buy(monkeypatch, bucket: str) -> None:
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
                "order_id": "OD1",
            }

        def daily_order_fills(
            self,
            *,
            code: str = "",
            order_id: str = "",
            side: str = "00",
        ) -> list[dict[str, int]]:
            return [{"filled_qty": self.placed_qty[0]}]

    client = Client()
    order = PensionOrderPlan("BUY", "0048J0", bucket, 10, 10_000, 100_000, "cash-like buy")

    assert execute_orders(client, [order]) == 0
    assert client.placed_qty == [10]


def test_final_cash_sweep_buy_plan_uses_cash_sweep_strategy() -> None:
    class Client:
        @staticmethod
        def buy_order_capacity(code: str, *, price: int, order_type: str) -> dict[str, int]:
            return {"nrcvb_buy_qty": 10, "nrcvb_buy_amt": 1_000_000}

    signal = QuarterlyMarketSignal(
        regime="neutral",
        reference_return_pct=0.0,
        kospi_return_pct=0.0,
        nasdaq_return_pct=0.0,
        selected_momentum_code="",
    )
    assets = [
        PensionAsset("360200", "sp500", "ACE 미국S&P500"),
        PensionAsset("440650", "parking", "파킹 ETF"),
    ]

    plan, orderable_cash = build_final_buy_plan(
        client=Client(),
        env={
            "PENSION_REBALANCE_ORDER_CASH_BUFFER_PCT": "0.05",
            "PENSION_REBALANCE_PARKING_CODE": "440650",
        },
        holdings=[PensionHolding("OTHER", "기존 보유", 1, 1_000_000, 1_000_000)],
        cash=120_000,
        assets=assets,
        prices={"360200": 100_000, "440650": 10_000},
        signal=signal,
        min_order_amount=50_000,
        trend_exit_step_pct=1.0 / 3.0,
        reserved_cash_amount=0,
        job="CASH_SWEEP",
    )

    assert orderable_cash == 114_000
    assert [(order.side, order.code, order.bucket, order.qty) for order in plan.orders] == [
        ("BUY", "360200", "sp500", 1)
    ]


def test_cash_sweep_entrypoint_does_not_build_regular_rebalance_plan(monkeypatch) -> None:
    signal = QuarterlyMarketSignal(
        regime="rising",
        reference_return_pct=1.0,
        kospi_return_pct=1.0,
        nasdaq_return_pct=1.0,
        selected_momentum_code="",
    )
    cash_sweep_plan = PensionRebalancePlan(
        regime="neutral",
        total_value=120_000,
        cash=120_000,
        target_weights={"sp500": 0.0, "momentum": 0.0, "bond": 0.0, "parking": 0.0, "other": 0.0},
        current_values={"sp500": 0, "momentum": 0, "bond": 0, "parking": 0, "other": 0},
        orders=[],
        estimated_cash_after_orders=120_000,
    )

    class Client:
        @staticmethod
        def balance() -> tuple[list[PensionHolding], int]:
            return [], 120_000

    monkeypatch.setattr(pension_script, "PensionKISClient", lambda env: Client())
    monkeypatch.setattr(pension_script, "resolve_quarterly_signal", lambda *args: signal)
    monkeypatch.setattr(pension_script, "assets_from_env", lambda *args, **kwargs: [])
    monkeypatch.setattr(pension_script, "validate_buyable_assets", lambda **kwargs: [])
    monkeypatch.setattr(pension_script, "refresh_prices", lambda *args: {})
    monkeypatch.setattr(
        pension_script,
        "build_pension_cash_sweep_plan",
        lambda **kwargs: cash_sweep_plan,
    )
    monkeypatch.setattr(
        pension_script,
        "build_pension_rebalance_plan",
        lambda **kwargs: pytest.fail("cash sweep must not use regular rebalance plan"),
    )

    args = SimpleNamespace(
        execute=False,
        cash_sweep=True,
        no_sells=False,
        if_drift=False,
        regime="auto",
        min_order_amount=50_000,
    )

    assert pension_script._run_pension_rebalance(args, {}) == 0
