from .trading_engine_support import *  # noqa: F401,F403

from backend.services.trading_engine.day_stop_review import (
    DayOvernightCarryReviewResult,
    DayStopReviewResult,
)

def test_reconcile_state_updates_qty_and_avg_price_from_broker_snapshot() -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = [{"code": "005930", "qty": 3, "avg_price": 98_000.0}]
    state = new_state("20260415")
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-14T09:00:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=105_000.0,
        entry_date="20260414",
    )
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260415",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
    )

    pos = state.open_positions["005930"]
    assert pos.qty == 3
    assert pos.entry_price == 98_000.0
    assert journal_rows[0][0] == "STATE_RECONCILE_UPDATE"
    assert notifications == ["[상태동기화][보정] 005930 수량=5->3 평균가=100000->98000"]

def test_reconcile_state_drop_reports_broker_absence_without_estimated_exit_reason() -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = []
    api._quotes["018880"] = {"price": 4_352, "change_pct": 3.0}
    state = new_state("20260421")
    state.open_positions["018880"] = PositionState(
        type="T",
        entry_time="2026-04-21T09:16:00",
        entry_price=4_225.0,
        qty=44,
        highest_price=4_352.0,
        entry_date="20260421",
    )
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260421",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
        config=TradeEngineConfig(day_take_profit_pct=0.03),
        now=datetime(2026, 4, 21, 9, 40, 0),
    )

    assert "018880" not in state.open_positions
    assert journal_rows[0][0] == "STATE_RECONCILE_DROP"
    assert journal_rows[0][1]["reason"] == "BROKER_POSITION_MISSING"
    assert journal_rows[0][1]["last_quote_price"] == 4352.0
    assert "estimated_reason" not in journal_rows[0][1]
    assert "estimated_pnl_pct" not in journal_rows[0][1]
    assert notifications == [
        "[상태동기화][정리] 018880 로컬수량=44 브로커수량=0 기준=브로커계좌조회 마지막가=4352"
    ]

def test_reconcile_state_drop_links_pending_exit_order_without_estimated_pnl() -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = []
    api._quotes["034020"] = {"price": 127_000, "change_pct": 1.8}
    state = new_state("20260424")
    state.open_positions["034020"] = PositionState(
        type="T",
        entry_time="2026-04-24T09:57:38",
        entry_price=124_800.0,
        qty=1,
        highest_price=127_950.0,
        entry_date="20260424",
    )
    state.pending_exit_orders["034020"] = {
        "strategy_type": "T",
        "reason": "LOCK",
        "order_id": "0020845000",
        "qty": 1,
        "order_time": "110025",
    }
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260424",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
        now=datetime(2026, 4, 24, 11, 2, 42),
    )

    assert "034020" not in state.open_positions
    assert "034020" not in state.pending_exit_orders
    assert journal_rows[0][0] == "STATE_RECONCILE_DROP"
    assert journal_rows[0][1]["exit_reason"] == "LOCK"
    assert journal_rows[0][1]["exit_order_id"] == "0020845000"
    assert "estimated_pnl_pct" not in journal_rows[0][1]
    assert notifications == [
        "[상태동기화][정리] 034020 로컬수량=1 브로커수량=0 기준=브로커계좌조회 "
        "마지막가=127000 로컬평단=124800 마지막가기준손익=+1.76% "
        "주문사유=수익보전 이탈 주문번호=0020845000"
    ]

def test_reconcile_state_drop_links_pending_exit_fill_from_daily_ccld() -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    class FillLookupAPI(FakeAPI):
        def daily_order_fills(self, **kwargs) -> list[dict]:
            assert kwargs["start_date"] == "20260508"
            assert kwargs["end_date"] == "20260508"
            assert kwargs["code"] == "319400"
            assert kwargs["order_id"] == "0008965100"
            assert kwargs["side"] == "01"
            return [
                {
                    "order_id": "0008965100",
                    "code": "319400",
                    "filled_qty": 8,
                    "avg_price": 35_400.0,
                }
            ]

    api = FillLookupAPI()
    api._positions = []
    api._quotes["319400"] = {"price": 35_400, "change_pct": -1.1}
    state = new_state("20260508")
    state.open_positions["319400"] = PositionState(
        type="T",
        entry_time="2026-05-08T09:08:00",
        entry_price=35_800.0,
        qty=8,
        highest_price=36_300.0,
        entry_date="20260508",
        locked_profit_pct=0.005,
    )
    state.pending_exit_orders["319400"] = {
        "strategy_type": "T",
        "reason": "LOCK",
        "order_id": "0008965100",
        "qty": 8,
        "order_time": "091500",
    }
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260508",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
        now=datetime(2026, 5, 8, 9, 16, 0),
    )

    assert "319400" not in state.open_positions
    assert journal_rows[0][0] == "STATE_RECONCILE_DROP"
    assert journal_rows[0][1]["exit_fill_qty"] == 8
    assert journal_rows[0][1]["exit_fill_avg_price"] == 35_400.0
    assert round(journal_rows[0][1]["exit_fill_pnl_pct"], 4) == -1.1173
    assert state.day_losses_today == 1
    assert state.day_consecutive_losses_today == 1
    assert state.consecutive_losses_today == 1
    assert state.day_realized_pnl_today == -3_200.0
    assert state.realized_pnl_today == -3_200.0
    assert state.realized_pnl_total == -3_200.0
    assert notifications == [
        "[상태동기화][정리] 319400 로컬수량=8 브로커수량=0 기준=브로커계좌조회 "
        "마지막가=35400 로컬평단=35800 마지막가기준손익=-1.12% "
        "체결수량=8 체결가=35400 체결손익=-1.12% "
        "주문사유=손절 주문번호=0008965100"
    ]

def test_reconcile_state_drop_counts_stoploss_fill_for_day_reentry_block() -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    class FillLookupAPI(FakeAPI):
        def daily_order_fills(self, **kwargs) -> list[dict]:
            assert kwargs["code"] == "047040"
            assert kwargs["order_id"] == "0023221400"
            return [
                {
                    "order_id": "0023221400",
                    "code": "047040",
                    "filled_qty": 8,
                    "avg_price": 26_550.0,
                }
            ]

    api = FillLookupAPI()
    api._positions = []
    api._quotes["047040"] = {"price": 26_600, "change_pct": 18.0}
    state = new_state("20260616")
    state.open_positions["047040"] = PositionState(
        type="T",
        entry_time="2026-06-16T13:04:04",
        entry_price=27_200.0,
        qty=8,
        highest_price=27_500.0,
        entry_date="20260616",
    )
    state.pending_exit_orders["047040"] = {
        "strategy_type": "T",
        "reason": "SL",
        "order_id": "0023221400",
        "qty": 8,
        "order_time": "133151",
    }

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260616",
        journal=lambda event, **fields: None,
        notify_text=lambda text: None,
        now=datetime(2026, 6, 16, 13, 32, 0),
    )

    assert state.day_losses_today == 1
    assert state.day_consecutive_losses_today == 1
    assert state.consecutive_losses_today == 1
    assert state.day_realized_pnl_today == -5_200.0
    assert state.realized_pnl_today == -5_200.0
    assert get_day_stoploss_codes_today(state) == {"047040"}

def test_reconcile_state_adds_broker_only_position_using_day_journal_hint(tmp_path) -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = [{"code": "222080", "qty": 12, "avg_price": 17_250.0, "current_price": 16_540}]
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = output_dir / "trade_journal_20260422.jsonl"
    journal_path.write_text(
        (
            '{"ts":"2026-04-22T09:15:40+09:00","event":"DAY_CHART_REVIEW",'
            '"asof_date":"20260422","selected_code":"222080","approved_codes":"222080","summary":"ENTER"}\n'
        ),
        encoding="utf-8",
    )

    state = new_state("20260422")
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260422",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
        config=TradeEngineConfig(output_dir=str(output_dir)),
        now=datetime(2026, 4, 22, 9, 36, 0),
    )

    pos = state.open_positions["222080"]
    assert pos.type == "T"
    assert pos.qty == 12
    assert pos.entry_price == 17_250.0
    assert state.day_entries_today == 1
    assert "222080" in state.blacklist_today
    assert journal_rows[0][0] == "STATE_RECONCILE_ADD"
    assert journal_rows[0][1]["reason"] == "BROKER_POSITION_FOUND_DURING_POLLING_SYNC"
    assert notifications == ["[상태동기화][신규반영] 222080 전략=단타 수량=12 평균가=17250 기준=브로커"]

def test_reconcile_state_skips_broker_only_position_without_hint(tmp_path) -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = [{"code": "222080", "qty": 12, "avg_price": 17_250.0, "current_price": 16_540}]
    state = new_state("20260422")
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260422",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
        config=TradeEngineConfig(output_dir=str(tmp_path / "output")),
        now=datetime(2026, 4, 22, 9, 36, 0),
    )

    assert "222080" not in state.open_positions
    assert journal_rows == [
        (
            "UNKNOWN_BROKER_POSITION",
            {
                "asof_date": "20260422",
                "code": "222080",
                "qty": 12,
                "reason": "BROKER_ONLY_WITHOUT_HINT",
            },
        )
    ]
    assert notifications == ["[상태동기화][외부포지션감지] 222080 수량=12 힌트없음 수동확인필요"]

def test_save_state_roundtrip_uses_atomic_replace(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state = new_state("20260415")
    state.day_realized_pnl_today = -3_200.0
    state.day_consecutive_losses_today = 1
    state.swing_consecutive_losses_today = 2
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-14T09:00:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=105_000.0,
        entry_date="20260414",
    )

    save_state(str(state_path), state)
    loaded = load_state(str(state_path))

    assert loaded.trade_date == "20260415"
    assert loaded.day_realized_pnl_today == -3_200.0
    assert loaded.day_consecutive_losses_today == 1
    assert loaded.swing_consecutive_losses_today == 2
    assert loaded.open_positions["005930"].qty == 5
    assert state_path.read_text(encoding="utf-8").endswith("\n")

def test_reconcile_state_records_unknown_broker_only_position_once_per_day(tmp_path) -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = [{"code": "222080", "qty": 12, "avg_price": 17_250.0}]
    state = new_state("20260422")
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260422",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
        config=TradeEngineConfig(output_dir=str(tmp_path / "output")),
        now=datetime(2026, 4, 22, 9, 36, 0),
    )
    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260422",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
        config=TradeEngineConfig(output_dir=str(tmp_path / "output")),
        now=datetime(2026, 4, 22, 10, 5, 0),
    )

    assert state.open_positions == {}
    assert state.unknown_broker_positions == {"222080": "20260422"}
    assert [event for event, _ in journal_rows] == ["UNKNOWN_BROKER_POSITION"]
    assert notifications == ["[상태동기화][외부포지션감지] 222080 수량=12 힌트없음 수동확인필요"]

def test_reconcile_state_promotes_pending_entry_order_to_position(tmp_path) -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = [{"code": "222080", "qty": 12, "avg_price": 17_250.0}]
    state = new_state("20260422")
    state.pending_entry_orders["222080"] = "T"

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260422",
        journal=lambda *args, **kwargs: None,
        notify_text=lambda *_args, **_kwargs: None,
        config=TradeEngineConfig(output_dir=str(tmp_path / "output")),
        now=datetime(2026, 4, 22, 9, 36, 0),
    )

    assert "222080" in state.open_positions
    assert state.open_positions["222080"].type == "T"
    assert "222080" not in state.pending_entry_orders

def test_handle_open_orders_cancels_only_stale_buy_orders() -> None:
    from backend.services.trading_engine.execution import handle_open_orders

    class OpenOrderAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.cancelled: list[str] = []

        def open_orders(self) -> list[dict]:
            return [
                {"order_id": "buy-1", "code": "005930", "side": "BUY", "remaining_qty": 1, "order_time": "090000"},
                {"order_id": "sell-1", "code": "005930", "side": "SELL", "remaining_qty": 1, "order_time": "090000"},
                {"order_id": "done-1", "code": "005930", "side": "BUY", "remaining_qty": 0, "status": "FILLED", "order_time": "090000"},
            ]

        def cancel_order(self, order_id: str) -> dict:
            self.cancelled.append(order_id)
            return {"order_id": order_id}

    api = OpenOrderAPI()
    result = handle_open_orders(api, timeout_sec=30, now=datetime(2026, 4, 22, 9, 5, 0))

    assert api.cancelled == ["buy-1"]
    assert result["cancelled"] == 1
    assert result["skipped_exit"] == 1

def test_load_state_recovers_from_corrupt_json(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{broken", encoding="utf-8")

    loaded = load_state(str(state_path))

    assert loaded.state_recovery_required is True
    assert loaded.state_recovery_reason == "STATE_LOAD_CORRUPT"
    backups = list(tmp_path.glob("state.json.corrupt.*"))
    assert len(backups) == 1
    assert not state_path.exists()

def test_load_state_skips_invalid_open_position_entries(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "trade_date": "20260415",
                "week_id": "2026-W16",
                "open_positions": {
                    "005930": {
                        "type": "S",
                        "entry_time": "2026-04-14T09:00:00",
                        "entry_price": 100000.0,
                        "qty": 5,
                        "highest_price": 105000.0,
                        "entry_date": "20260414",
                    },
                    "BAD001": {
                        "type": "T",
                        "entry_time": "2026-04-14T09:00:00",
                        "entry_price": "oops",
                        "qty": "x",
                        "entry_date": "20260414",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_state(str(state_path))

    assert set(loaded.open_positions) == {"005930"}

def test_rollover_state_prunes_closed_day_carry_keys() -> None:
    from backend.services.trading_engine.state import rollover_state_for_date

    state = new_state("20260424")
    state.day_realized_pnl_today = -5_000.0
    state.day_consecutive_losses_today = 2
    state.swing_consecutive_losses_today = 1
    state.open_positions["005930"] = PositionState(
        type="T",
        entry_time="2026-04-24T10:00:00",
        entry_price=100000.0,
        qty=1,
        highest_price=100000.0,
        entry_date="20260424",
    )
    state.day_overnight_carry_positions = {
        "005930:2026-04-24T10:00:00": "20260424",
        "000660:2026-04-24T10:05:00": "20260424",
    }

    rolled = rollover_state_for_date(state, "20260425")

    assert rolled.day_realized_pnl_today == 0.0
    assert rolled.day_consecutive_losses_today == 0
    assert rolled.swing_consecutive_losses_today == 0
    assert rolled.day_overnight_carry_positions == {"005930:2026-04-24T10:00:00": "20260424"}

def test_run_once_skips_when_run_lock_already_held(tmp_path) -> None:
    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    assert bot._run_lock.acquire(blocking=False) is True
    try:
        result = bot.run_once(now=datetime(2026, 4, 29, 9, 10))
    finally:
        bot._run_lock.release()

    assert result == {"status": "SKIP", "reason": "RUN_ALREADY_IN_PROGRESS"}

def test_run_once_releases_run_lock_after_error(tmp_path) -> None:
    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)

    with patch("backend.services.trading_engine.bot.is_trading_day", side_effect=RuntimeError("boom")):
        result = bot.run_once(now=datetime(2026, 4, 29, 9, 10))

    assert result["status"] == "ERROR"
    assert bot._run_lock.acquire(blocking=False) is True
    bot._run_lock.release()
