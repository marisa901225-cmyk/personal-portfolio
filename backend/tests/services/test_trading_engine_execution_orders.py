from .trading_engine_support import *  # noqa: F401,F403

from backend.services.trading_engine.day_stop_review import (
    DayOvernightCarryReviewResult,
    DayStopReviewResult,
)

def test_exit_position_does_not_book_fill_from_order_acceptance_only() -> None:
    class PendingOnlyAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": True, "order_id": f"{side}-{code}", "msg": "주문 접수"}

    api = PendingOnlyAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.0}
    api._positions = [{"code": "005930", "qty": 10, "avg_price": 100_000.0}]
    state = new_state("20260415")
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-14T09:00:00",
        entry_price=100_000.0,
        qty=10,
        highest_price=105_000.0,
        entry_date="20260414",
    )

    result = exit_position(
        api,
        state,
        code="005930",
        reason="TP",
        now=datetime(2026, 4, 15, 10, 0),
    )

    assert result is None
    assert state.open_positions["005930"].qty == 10
    assert state.realized_pnl_today == 0.0

def test_exit_position_reports_order_acceptance_when_fill_is_not_confirmed() -> None:
    class PendingOnlyAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}",
                "order_time": "110025",
                "msg": "주문 접수",
            }

    api = PendingOnlyAPI()
    api._quotes["034020"] = {"price": 126_600, "change_pct": 1.4}
    api._positions = [{"code": "034020", "qty": 1, "avg_price": 124_800.0}]
    state = new_state("20260424")
    state.open_positions["034020"] = PositionState(
        type="T",
        entry_time="2026-04-24T09:57:38",
        entry_price=124_800.0,
        qty=1,
        highest_price=127_950.0,
        entry_date="20260424",
    )
    accepted_orders: list[dict] = []

    result = exit_position(
        api,
        state,
        code="034020",
        reason="LOCK",
        now=datetime(2026, 4, 24, 11, 0, 25),
        on_order_accepted=accepted_orders.append,
    )

    assert result is None
    assert accepted_orders == [
        {
            "code": "034020",
            "side": "SELL",
            "qty": 1,
            "reason": "LOCK",
            "order_id": "SELL-034020",
            "order_time": "110025",
            "order_type": "MKT",
            "price": None,
            "raw": {
                "success": True,
                "order_id": "SELL-034020",
                "order_time": "110025",
                "msg": "주문 접수",
            },
        }
    ]
    assert state.open_positions["034020"].qty == 1
    assert state.realized_pnl_today == 0.0

def test_handle_open_orders_only_cancels_stale_orders() -> None:
    class OpenOrderAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._open_orders = [
                {"order_id": "old-1", "order_time": "090000", "remaining_qty": 3, "side": "BUY"},
                {"order_id": "recent-1", "order_time": "090045", "remaining_qty": 2, "side": "BUY"},
                {"order_id": "filled-1", "order_time": "085900", "remaining_qty": 0, "status": "FILLED", "side": "BUY"},
                {"order_id": "unknown-1", "remaining_qty": 1, "side": "BUY"},
            ]
            self.cancelled_ids: list[str] = []

        def open_orders(self) -> list[dict]:
            return list(self._open_orders)

        def cancel_order(self, order_id: str) -> dict:
            self.cancelled_ids.append(order_id)
            return {"order_id": order_id, "status": "cancelled"}

    from backend.services.trading_engine.execution import handle_open_orders

    api = OpenOrderAPI()
    result = handle_open_orders(
        api,
        timeout_sec=30,
        now=datetime(2026, 4, 15, 9, 1, 0),
    )

    assert api.cancelled_ids == ["old-1"]
    assert result == {
        "cancelled": 1,
        "skipped_recent": 1,
        "skipped_unknown_time": 1,
        "skipped_exit": 0,
    }
