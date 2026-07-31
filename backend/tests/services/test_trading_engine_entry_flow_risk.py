from .trading_engine_support import *  # noqa: F401,F403

def test_swing_position_does_not_exit_on_day_lock_retrace(tmp_path) -> None:
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    position = PositionState(
        type="S",
        entry_time="2026-02-16T09:10:00",
        entry_price=100_000.0,
        qty=7,
        highest_price=105_000.0,
        entry_date="20260216",
        locked_profit_pct=0.043182,
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=103_600.0,
        now=datetime(2026, 2, 16, 13, 14),
        config=cfg,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.036

def test_day_position_arms_profit_lock_and_waits_for_intraday_trend_break() -> None:
    cfg = TradeEngineConfig(
        day_lock_profit_trigger_pct=0.009,
        day_lock_profit_floor_pct=0.002,
        day_lock_retrace_gap_pct=0.006,
        day_lock_requires_intraday_trend_break=True,
    )
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=101_500.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=101_500.0,
        now=datetime(2026, 2, 16, 9, 20),
        config=cfg,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.015
    assert abs(float(position.locked_profit_pct or 0.0) - 0.009) < 1e-9

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=100_800.0,
        now=datetime(2026, 2, 16, 9, 24),
        config=cfg,
        day_lock_intraday_trend_broken=False,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.008

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=100_800.0,
        now=datetime(2026, 2, 16, 9, 25),
        config=cfg,
        day_lock_intraday_trend_broken=True,
    )

    assert exit_now is True
    assert reason == "LOCK"
    assert round(pnl_pct, 4) == 0.008

def test_day_position_volatility_aware_lock_allows_early_pullback() -> None:
    cfg = TradeEngineConfig(
        day_lock_profit_trigger_pct=0.009,
        day_lock_profit_floor_pct=0.005,
        day_lock_retrace_gap_pct=0.006,
        day_take_profit_pct=0.050,
    )
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=101_800.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=101_800.0,
        now=datetime(2026, 2, 16, 9, 12),
        config=cfg,
        day_lock_retrace_gap_pct_override=0.013,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.018
    assert abs(float(position.locked_profit_pct or 0.0) - 0.005) < 1e-9

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=100_900.0,
        now=datetime(2026, 2, 16, 9, 16),
        config=cfg,
        day_lock_retrace_gap_pct_override=0.013,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.009

def test_day_stop_loss_default_is_one_point_five_percent() -> None:
    cfg = TradeEngineConfig()
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=100_000.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=98_600.0,
        now=datetime(2026, 2, 16, 9, 24),
        config=cfg,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == -0.014

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=98_500.0,
        now=datetime(2026, 2, 16, 9, 25),
        config=cfg,
    )

    assert exit_now is True
    assert reason == "SL"
    assert round(pnl_pct, 4) == -0.015

def test_day_stop_loss_can_use_intraday_volatility_override() -> None:
    cfg = TradeEngineConfig(day_stop_loss_pct=-0.015)
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=100_000.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=98_400.0,
        now=datetime(2026, 2, 16, 9, 24),
        config=cfg,
        day_stop_loss_pct_override=-0.020,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == -0.016

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=98_000.0,
        now=datetime(2026, 2, 16, 9, 25),
        config=cfg,
        day_stop_loss_pct_override=-0.020,
    )

    assert exit_now is True
    assert reason == "SL"
    assert round(pnl_pct, 4) == -0.02

def test_day_hold_match_does_not_tighten_lock_to_full_profit(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005880"] = {"price": 101_800, "change_pct": 1.8}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    bot.state.open_positions["005880"] = PositionState(
        type="T",
        entry_time="2026-02-16T09:08:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=100_000.0,
        entry_date="20260216",
        locked_profit_pct=0.005,
    )

    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame([{"code": "005880"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["005880"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 12),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005880": api.quote("005880")},
            news_signal=None,
        )

    assert api.order_calls == []
    assert "005880" in bot.state.open_positions
    assert abs(float(bot.state.open_positions["005880"].locked_profit_pct or 0.0) - 0.005) < 1e-9
    assert abs(float(bot.state.open_positions["005880"].highest_price or 0.0) - 101_800.0) < 1e-9

def test_day_position_keeps_day_lock_rules_when_matching_swing_candidate(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["475150"] = {"price": 100_800, "change_pct": 0.8}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_chart_review_enabled=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    bot.state.open_positions["475150"] = PositionState(
        type="T",
        entry_time="2026-02-16T09:08:00",
        entry_price=100_000.0,
        qty=3,
        highest_price=100_000.0,
        entry_date="20260216",
    )

    candidates = SimpleNamespace(
        model=pd.DataFrame([{"code": "475150", "name": "후보종목"}]),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=["475150"]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 9, 20),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"475150": api.quote("475150")},
        )

    assert api.order_calls == []
    assert "475150" in bot.state.open_positions
    assert bot.state.open_positions["475150"].locked_profit_pct is None
    assert abs(float(bot.state.open_positions["475150"].highest_price or 0.0) - 100_800.0) < 1e-9

    api._quotes["475150"] = {"price": 100_700, "change_pct": 0.7}
    bot.monitor_positions(now=datetime(2026, 2, 16, 9, 22))

    assert not any(call["side"] == "SELL" and call["code"] == "475150" for call in api.order_calls)
    assert "475150" in bot.state.open_positions

def test_day_entry_windows_progress_across_four_intraday_slots() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")

    ok_first_window, reason_first_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )
    ok_third_window_before_fill, reason_third_window_before_fill = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    state.day_entries_today = 1
    state.day_entry_windows_used_today = {0}
    ok_second_morning, reason_second_morning = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )
    ok_second_window, reason_second_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 10, 0),
        config=cfg,
    )

    state.day_entries_today = 2
    state.day_entry_windows_used_today = {0, 1}
    ok_third_window, reason_third_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )
    ok_fourth_window_before_third_fill, reason_fourth_window_before_third_fill = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 14, 0),
        config=cfg,
    )

    state.day_entries_today = 3
    state.day_entry_windows_used_today = {0, 1, 2}
    ok_fourth_window, reason_fourth_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 14, 0),
        config=cfg,
    )

    assert ok_first_window is True
    assert reason_first_window == "OK"
    assert ok_third_window_before_fill is True
    assert reason_third_window_before_fill == "OK"
    assert ok_second_morning is False
    assert reason_second_morning == "ENTRY_WINDOW_CLOSED"
    assert ok_second_window is True
    assert reason_second_window == "OK"
    assert ok_third_window is True
    assert reason_third_window == "OK"
    assert ok_fourth_window_before_third_fill is True
    assert reason_fourth_window_before_third_fill == "OK"
    assert ok_fourth_window is True
    assert reason_fourth_window == "OK"

def test_day_afternoon_entry_blocks_after_two_stoploss_sized_losses() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")
    state.day_entries_today = 2
    state.day_realized_pnl_today = -6_000.0

    ok_afternoon_blocked, reason_afternoon_blocked = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    state.day_realized_pnl_today = -5_900.0
    ok_afternoon_allowed, reason_afternoon_allowed = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    assert ok_afternoon_blocked is False
    assert reason_afternoon_blocked == "DAY_AFTERNOON_LOSS_LIMIT"
    assert ok_afternoon_allowed is True
    assert reason_afternoon_allowed == "OK"


def test_daily_max_loss_blocks_day_entry_but_allows_swing_entry() -> None:
    cfg = TradeEngineConfig(
        initial_capital=1_000_000,
        daily_max_loss_pct=-0.02,
        max_swing_positions=1,
    )
    state = new_state("20260630")
    state.day_realized_pnl_today = -36_000.0

    ok_day, reason_day = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 6, 30, 13, 10),
        config=cfg,
    )
    ok_swing, reason_swing = can_enter(
        "S",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 6, 30, 13, 10),
        config=cfg,
    )

    assert ok_day is False
    assert reason_day == "DAILY_MAX_LOSS"
    assert ok_swing is True
    assert reason_swing == "OK"


def test_swing_losses_do_not_block_day_entry_risk_limits() -> None:
    cfg = TradeEngineConfig(
        initial_capital=1_000_000,
        daily_max_loss_pct=-0.02,
        max_consecutive_losses=2,
    )
    state = new_state("20260731")
    state.realized_pnl_today = -36_000.0
    state.consecutive_losses_today = 2
    state.day_realized_pnl_today = 0.0
    state.day_consecutive_losses_today = 0

    ok, reason = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 7, 31, 9, 10),
        config=cfg,
    )

    assert ok is True
    assert reason == "OK"


def test_day_entry_limit_expands_by_one_slot_when_intraday_win_rate_is_healthy() -> None:
    cfg = TradeEngineConfig(
        max_day_entries_per_day=4,
        day_conditional_extra_entries_enabled=True,
        day_conditional_extra_entries=2,
    )
    state = new_state("20260216")
    state.day_entries_today = 4
    state.day_wins_today = 2
    state.day_losses_today = 0
    state.day_realized_pnl_today = 8_000.0
    state.day_entry_windows_used_today = {0, 1, 2}
    state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:05:00",
        entry_price=400_000.0,
        qty=1,
        highest_price=400_000.0,
        entry_date="20260216",
    )

    ok_extra_slot, reason_extra_slot = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 14, 0),
        config=cfg,
    )

    state.day_entries_today = 5
    ok_hard_cap, reason_hard_cap = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 14, 0),
        config=cfg,
    )

    assert ok_extra_slot is True
    assert reason_extra_slot == "OK"
    assert ok_hard_cap is False
    assert reason_hard_cap == "MAX_DAY_ENTRIES_DAY"


def test_day_entry_conditional_extra_requires_unused_swing_budget() -> None:
    cfg = TradeEngineConfig(
        max_day_entries_per_day=1,
        day_conditional_extra_entries_enabled=True,
        day_conditional_extra_entries=2,
        day_conditional_extra_min_closed_trades=0,
        day_conditional_extra_min_win_rate=0.0,
    )
    state = new_state("20260216")
    state.day_entries_today = 1
    state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:05:00",
        entry_price=800_000.0,
        qty=1,
        highest_price=800_000.0,
        entry_date="20260216",
    )

    ok_full_swing, reason_full_swing = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )

    state.open_positions["SWING01"].entry_price = 600_000.0
    ok_unused_swing, reason_unused_swing = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )

    assert ok_full_swing is False
    assert reason_full_swing == "MAX_DAY_ENTRIES_DAY"
    assert ok_unused_swing is True
    assert reason_unused_swing == "OK"


def test_day_entry_conditional_extra_does_not_open_for_small_unused_swing_budget() -> None:
    cfg = TradeEngineConfig(
        max_day_entries_per_day=1,
        day_conditional_extra_entries_enabled=True,
        day_conditional_extra_entries=2,
        day_conditional_extra_min_closed_trades=0,
        day_conditional_extra_min_win_rate=0.0,
    )
    state = new_state("20260216")
    state.day_entries_today = 1
    state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:05:00",
        entry_price=750_000.0,
        qty=1,
        highest_price=750_000.0,
        entry_date="20260216",
    )

    ok, reason = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )

    assert ok is False
    assert reason == "MAX_DAY_ENTRIES_DAY"


def test_day_position_second_slot_depends_on_unused_swing_budget() -> None:
    cfg = TradeEngineConfig(
        max_day_entries_per_day=16,
        max_day_positions=2,
        day_conditional_extra_entries_enabled=True,
        day_conditional_extra_entries=1,
        day_conditional_extra_min_closed_trades=0,
        day_conditional_extra_min_win_rate=0.0,
    )
    state = new_state("20260216")
    state.day_entries_today = 1
    state.open_positions["DAY01"] = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=200_000.0,
        qty=1,
        highest_price=200_000.0,
        entry_date="20260216",
    )
    state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:05:00",
        entry_price=750_000.0,
        qty=1,
        highest_price=750_000.0,
        entry_date="20260216",
    )

    ok_small_leftover, reason_small_leftover = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )

    state.open_positions["SWING01"].entry_price = 600_000.0
    ok_enough_leftover, reason_enough_leftover = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )

    assert ok_small_leftover is False
    assert reason_small_leftover == "MAX_DAY_POSITIONS"
    assert ok_enough_leftover is True
    assert reason_enough_leftover == "OK"


def test_day_position_second_slot_opens_when_available_cash_exceeds_floor() -> None:
    cfg = TradeEngineConfig(
        max_day_entries_per_day=16,
        max_day_positions=2,
        day_conditional_extra_entries_enabled=True,
        day_conditional_extra_entries=1,
        day_conditional_extra_min_closed_trades=0,
        day_conditional_extra_min_win_rate=0.0,
    )
    state = new_state("20260216")
    state.day_entries_today = 1
    state.open_positions["DAY01"] = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=200_000.0,
        qty=1,
        highest_price=200_000.0,
        entry_date="20260216",
    )
    state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:05:00",
        entry_price=722_000.0,
        qty=1,
        highest_price=722_000.0,
        entry_date="20260216",
    )

    ok, reason = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
        available_cash_krw=247_898,
    )

    assert ok is True
    assert reason == "OK"


def test_day_entry_limit_stays_capped_when_intraday_win_rate_is_weak() -> None:
    cfg = TradeEngineConfig(
        max_day_entries_per_day=4,
        day_conditional_extra_entries_enabled=True,
        day_conditional_extra_entries=2,
    )
    state = new_state("20260216")
    state.day_entries_today = 4
    state.day_wins_today = 1
    state.day_losses_today = 1
    state.realized_pnl_today = 8_000.0
    state.day_entry_windows_used_today = {0, 1, 2}

    ok, reason = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 14, 0),
        config=cfg,
    )

    assert ok is False
    assert reason == "MAX_DAY_ENTRIES_DAY"
