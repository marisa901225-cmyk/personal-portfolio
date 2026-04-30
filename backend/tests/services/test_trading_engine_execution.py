from .trading_engine_support import *  # noqa: F401,F403

from backend.services.trading_engine.day_stop_review import (
    DayOvernightCarryReviewResult,
    DayStopReviewResult,
)

def test_exit_position_caps_sell_qty_by_broker_sellable_amount() -> None:
    class SellableAPI(FakeAPI):
        def sell_order_capacity(self, code: str) -> dict:
            assert code == "440650"
            return {
                "ord_psbl_qty": 30,
                "hldg_qty": 50,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": price or self.quote(code).get("price", 0),
            }

    api = SellableAPI()
    api._quotes["440650"] = {"price": 12_500, "change_pct": 0.1}
    state = new_state("20260325")
    state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-25T10:00:00",
        entry_price=12_000.0,
        qty=50,
        highest_price=12_500.0,
        entry_date="20260325",
        bars_held=0,
    )

    result = exit_position(
        api,
        state,
        code="440650",
        reason="RISK_ON",
        now=datetime(2026, 3, 25, 10, 30),
    )

    assert result is not None
    assert result.qty == 30
    assert api.order_calls == [
        {"side": "SELL", "code": "440650", "qty": 30, "order_type": "MKT", "price": None}
    ]
    assert "440650" in state.open_positions
    assert state.open_positions["440650"].qty == 20
    assert state.realized_pnl_today == 15_000.0
    assert state.realized_pnl_total == 15_000.0

def test_monitor_positions_excludes_day_stoploss_symbol_after_third_loss(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["011930"] = {"price": 9_800, "change_pct": -2.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.day_stoploss_fail_counts["011930"] = 2
    bot.state.open_positions["011930"] = PositionState(
        type="T",
        entry_time="2026-04-07T09:05:00",
        entry_price=10_000.0,
        qty=10,
        highest_price=10_000.0,
        entry_date="20260407",
    )

    now = datetime(2026, 4, 7, 9, 30)
    bot.monitor_positions(now=now)

    assert "011930" not in bot.state.open_positions
    assert get_day_stoploss_fail_count(bot.state, "011930") == 3
    assert "011930" in get_day_stoploss_codes_today(bot.state)
    assert "011930" in bot.state.day_stoploss_excluded_codes
    assert "011930" in get_day_stoploss_excluded_codes(bot.state)
    assert "011930" in get_day_reentry_blocked_codes(bot.state)

def test_monitor_positions_tracks_day_stoploss_count_before_exclusion(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["011930"] = {"price": 9_800, "change_pct": -2.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.day_stoploss_fail_counts["011930"] = 1
    bot.state.open_positions["011930"] = PositionState(
        type="T",
        entry_time="2026-04-07T09:05:00",
        entry_price=10_000.0,
        qty=10,
        highest_price=10_000.0,
        entry_date="20260407",
    )

    now = datetime(2026, 4, 7, 9, 30)
    bot.monitor_positions(now=now)

    assert "011930" not in bot.state.open_positions
    assert get_day_stoploss_fail_count(bot.state, "011930") == 2
    assert "011930" in get_day_stoploss_codes_today(bot.state)
    assert "011930" not in bot.state.day_stoploss_excluded_codes
    assert "011930" not in get_day_stoploss_excluded_codes(bot.state)
    assert "011930" in get_day_reentry_blocked_codes(bot.state)

def test_monitor_positions_holds_day_stop_once_when_llm_approves_pullback(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    api._quotes["027360"] = {"price": 18_300, "change_pct": 20.0}
    api._intraday[("027360", "20260424")] = _make_intraday_bars(
        "20260424",
        [18_600.0, 18_520.0, 18_430.0],
        last_change_pct=20.0,
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_stop_loss_pct=-0.012,
        day_stop_llm_review_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260424"
    bot.state.open_positions["027360"] = PositionState(
        type="T",
        entry_time="2026-04-24T13:02:24",
        entry_price=18_540.0,
        qty=11,
        highest_price=18_700.0,
        entry_date="20260424",
    )

    review = DayStopReviewResult(
        decision="HOLD",
        confidence=0.82,
        reason="급등 후 얕은 눌림으로 판단",
        route="paid",
        raw_response={},
    )
    with patch(
        "backend.services.trading_engine.bot_position_management.review_day_stop_with_llm",
        return_value=review,
    ) as mocked_review:
        bot.monitor_positions(now=datetime(2026, 4, 24, 13, 36))

    mocked_review.assert_called_once()
    assert api.order_calls == []
    assert "027360" in bot.state.open_positions
    assert "027360:2026-04-24T13:02:24" in bot.state.day_stop_llm_reviewed_positions

def test_monitor_positions_exits_day_stop_after_llm_review_was_already_used(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    api._quotes["027360"] = {"price": 18_300, "change_pct": 20.0}
    api._intraday[("027360", "20260424")] = _make_intraday_bars(
        "20260424",
        [18_600.0, 18_520.0, 18_430.0],
        last_change_pct=20.0,
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_stop_loss_pct=-0.012,
        day_stop_llm_review_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260424"
    bot.state.day_stop_llm_reviewed_positions.add("027360:2026-04-24T13:02:24")
    bot.state.open_positions["027360"] = PositionState(
        type="T",
        entry_time="2026-04-24T13:02:24",
        entry_price=18_540.0,
        qty=11,
        highest_price=18_700.0,
        entry_date="20260424",
    )

    with patch(
        "backend.services.trading_engine.bot_position_management.review_day_stop_with_llm"
    ) as mocked_review:
        bot.monitor_positions(now=datetime(2026, 4, 24, 13, 40))

    mocked_review.assert_not_called()
    assert any(call["side"] == "SELL" and call["code"] == "027360" for call in api.order_calls)
    assert "027360" not in bot.state.open_positions

def test_monitor_positions_exits_day_stop_without_llm_at_hard_stop(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    api._quotes["027360"] = {"price": 18_100, "change_pct": 20.0}
    api._intraday[("027360", "20260424")] = _make_intraday_bars(
        "20260424",
        [18_600.0, 18_520.0, 18_430.0],
        last_change_pct=20.0,
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_stop_loss_pct=-0.012,
        day_stop_llm_review_enabled=True,
        day_stop_llm_hard_stop_pct=-0.022,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260424"
    bot.state.open_positions["027360"] = PositionState(
        type="T",
        entry_time="2026-04-24T13:02:24",
        entry_price=18_540.0,
        qty=11,
        highest_price=18_700.0,
        entry_date="20260424",
    )

    with patch(
        "backend.services.trading_engine.bot_position_management.review_day_stop_with_llm"
    ) as mocked_review:
        bot.monitor_positions(now=datetime(2026, 4, 24, 13, 40))

    mocked_review.assert_not_called()
    assert any(call["side"] == "SELL" and call["code"] == "027360" for call in api.order_calls)
    assert "027360" not in bot.state.open_positions

def test_monitor_positions_carries_last_day_position_once_when_llm_approves(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    api._quotes["009830"] = {"price": 49_200, "change_pct": 5.0}
    api._intraday[("009830", "20260424")] = _make_intraday_bars(
        "20260424",
        [49_000.0, 49_100.0, 49_200.0],
        start_time="151300",
        last_change_pct=5.0,
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_overnight_carry_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260424"
    bot.state.open_positions["009830"] = PositionState(
        type="T",
        entry_time="2026-04-24T13:55:00+09:00",
        entry_price=49_150.0,
        qty=4,
        highest_price=49_300.0,
        entry_date="20260424",
    )

    review = DayOvernightCarryReviewResult(
        decision="CARRY",
        confidence=0.78,
        reason="종가 흐름이 무너지지 않아 하루 유예 가능",
        route="paid",
        raw_response={},
    )
    with patch(
        "backend.services.trading_engine.bot_position_management.review_day_overnight_carry_with_llm",
        return_value=review,
    ) as mocked_review:
        bot.monitor_positions(now=datetime(2026, 4, 24, 15, 16))
        bot.force_exit_day_positions(now=datetime(2026, 4, 24, 15, 16))

    mocked_review.assert_called_once()
    assert api.order_calls == []
    assert bot.state.open_positions["009830"].type == "T"
    key = "009830:2026-04-24T13:55:00+09:00"
    assert bot.state.day_overnight_carry_positions[key] == "20260424"

def test_force_exit_day_position_sells_next_day_after_overnight_carry(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["009830"] = {"price": 49_200, "change_pct": 0.2}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_overnight_carry_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260427"
    key = "009830:2026-04-24T13:55:00+09:00"
    bot.state.day_overnight_carry_positions[key] = "20260424"
    bot.state.open_positions["009830"] = PositionState(
        type="T",
        entry_time="2026-04-24T13:55:00+09:00",
        entry_price=49_150.0,
        qty=4,
        highest_price=49_300.0,
        entry_date="20260424",
    )

    with patch(
        "backend.services.trading_engine.bot_position_management.review_day_overnight_carry_with_llm"
    ) as mocked_review:
        bot.force_exit_day_positions(now=datetime(2026, 4, 27, 15, 16))

    mocked_review.assert_not_called()
    assert any(call["side"] == "SELL" and call["code"] == "009830" for call in api.order_calls)
    assert "009830" not in bot.state.open_positions


def test_force_exit_day_position_skips_overnight_carry_before_long_market_closure(tmp_path) -> None:
    class HolidayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.next_open_calls: list[tuple[str, int]] = []

        def next_open_trading_day(self, date: str, max_lookahead_days: int = 14) -> str:
            self.next_open_calls.append((date, max_lookahead_days))
            return "20260928"

    api = HolidayAPI()
    api._quotes["009830"] = {"price": 49_200, "change_pct": 2.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_overnight_carry_enabled=True,
        day_overnight_carry_max_calendar_gap_days=3,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260923"
    bot.state.open_positions["009830"] = PositionState(
        type="T",
        entry_time="2026-09-23T13:55:00+09:00",
        entry_price=49_150.0,
        qty=4,
        highest_price=49_300.0,
        entry_date="20260923",
    )

    with patch(
        "backend.services.trading_engine.bot_position_management.review_day_overnight_carry_with_llm"
    ) as mocked_review:
        bot.force_exit_day_positions(now=datetime(2026, 9, 23, 15, 16))

    mocked_review.assert_not_called()
    assert api.next_open_calls == [("20260923", 14)]
    assert any(call["side"] == "SELL" and call["code"] == "009830" for call in api.order_calls)
    assert "009830" not in bot.state.open_positions


def test_day_stop_loss_still_wins_over_force_exit_time(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["009830"] = {"price": 48_400, "change_pct": -1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_stop_loss_pct=-0.012,
        day_overnight_carry_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260424"
    bot.state.open_positions["009830"] = PositionState(
        type="T",
        entry_time="2026-04-24T13:55:00+09:00",
        entry_price=49_150.0,
        qty=4,
        highest_price=49_300.0,
        entry_date="20260424",
    )

    with patch(
        "backend.services.trading_engine.bot_position_management.review_day_overnight_carry_with_llm"
    ) as mocked_review:
        bot.monitor_positions(now=datetime(2026, 4, 24, 15, 16))

    mocked_review.assert_not_called()
    assert any(call["side"] == "SELL" and call["code"] == "009830" for call in api.order_calls)
    assert "009830" not in bot.state.open_positions

def test_bot_skips_daytrade_reentry_after_same_day_stoploss_even_before_threshold(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 50_000, "change_pct": 1.5}
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.4}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.day_stoploss_fail_counts["011930"] = 1
    mark_day_stoploss_today(bot.state, code="011930")

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "80000000000", "close": 50000, "change_pct": "1.4", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000"},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "80000000000"},
            ]
        ),
        quote_codes=["011930", "005930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "limit", "price": 50_100}
    ]
    assert "011930" not in bot.state.open_positions
    assert "005930" in bot.state.open_positions

def test_monitor_positions_temporarily_excludes_swing_time_exit_symbol(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005930"] = {"price": 10_000, "change_pct": 0.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-07T09:05:00",
        entry_price=10_000.0,
        qty=10,
        highest_price=10_000.0,
        entry_date="20260324",
        bars_held=10,
    )

    now = datetime(2026, 4, 7, 10, 30)
    bot.monitor_positions(now=now)

    assert "005930" not in bot.state.open_positions
    assert "005930" in bot.state.swing_time_excluded_codes
    assert "005930" in get_swing_time_excluded_codes(bot.state)

def test_bot_skips_day_stoploss_excluded_symbol_on_next_daytrade_entry(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 1_000, "change_pct": 8.0}
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    for _ in range(cfg.day_stoploss_exclude_after_losses):
        record_day_stoploss_failure(
            bot.state,
            code="011930",
            exclude_after_losses=cfg.day_stoploss_exclude_after_losses,
        )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000", "close": 1000, "change_pct": "8.0", "is_etf": False},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "10000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000"},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "10000000000"},
            ]
        ),
        quote_codes=["011930", "005930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "limit", "price": 50_100}
    ]
    assert "011930" not in bot.state.open_positions
    assert "005930" in bot.state.open_positions

def test_bot_skips_blacklisted_symbol_on_same_day_reentry_candidate(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["027360"] = {"price": 50_000, "change_pct": 1.6}
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.blacklist_today.add("027360")

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "027360", "name": "아주IB투자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.6", "is_etf": False},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "80000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "027360", "name": "아주IB투자", "avg_value_5d": "90000000000"},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "80000000000"},
            ]
        ),
        quote_codes=["027360", "005930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "limit", "price": 50_100}
    ]
    assert "027360" not in bot.state.open_positions
    assert "005930" in bot.state.open_positions
