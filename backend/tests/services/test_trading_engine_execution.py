from .trading_engine_support import *  # noqa: F401,F403

from backend.services.trading_engine.day_stop_review import DayStopReviewResult

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

def test_bot_allows_daytrade_reentry_before_day_stoploss_threshold(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.day_stoploss_fail_counts["011930"] = cfg.day_stoploss_exclude_after_losses - 1

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["011930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "011930", "qty": 4, "order_type": "limit", "price": 50_100}
    ]
    assert "011930" in bot.state.open_positions
    assert bot.state.open_positions["011930"].type == "T"

def test_bot_skips_swing_time_excluded_symbol_on_next_swing_entry(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 50_000, "change_pct": 1.5}
    api._quotes["000660"] = {"price": 50_000, "change_pct": 1.4}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.swing_time_excluded_codes.add("011930")

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "011930",
                    "name": "신성이엔지",
                    "avg_value_20d": "900000000000",
                    "ma20": 48_000,
                    "ma60": 45_000,
                    "close": 50_000,
                    "change_pct": "1.5",
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "000660",
                    "name": "SK하이닉스",
                    "avg_value_20d": "800000000000",
                    "ma20": 48_000,
                    "ma60": 45_000,
                    "close": 50_000,
                    "change_pct": "1.4",
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_20d": "900000000000"},
                {"code": "000660", "name": "SK하이닉스", "avg_value_20d": "800000000000"},
            ]
        ),
        quote_codes=["011930", "000660"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "000660", "qty": 16, "order_type": "best", "price": None}
    ]
    assert "011930" not in bot.state.open_positions
    assert "000660" in bot.state.open_positions

def test_bot_allows_swing_entry_for_day_stoploss_excluded_symbol(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 50_000, "change_pct": 1.5}

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
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "011930",
                    "name": "신성이엔지",
                    "avg_value_20d": "800000000000",
                    "ma20": 48_000,
                    "ma60": 45_000,
                    "close": 50_000,
                    "change_pct": "1.5",
                    "is_etf": False,
                    "trend_tier": "strict",
                }
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_20d": "800000000000"},
            ]
        ),
        quote_codes=["011930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "011930", "qty": 16, "order_type": "best", "price": None}
    ]
    assert "011930" in bot.state.open_positions
    assert bot.state.open_positions["011930"].type == "S"

def test_day_entry_uses_strategy_cap_not_remaining_cash(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 250_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-04-08T09:05:00",
        entry_price=100_000.0,
        qty=8,
        highest_price=100_000.0,
        entry_date="20260408",
        bars_held=2,
    )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 4

def test_day_entry_adds_realized_profit_buffer_on_top_of_strategy_cap(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 260_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
        use_realized_profit_buffer=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.realized_pnl_total = 50_000.0

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 5, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 5

def test_day_entry_uses_account_basis_buffer_without_unrealized_gain(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 250_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}
    api._positions = [
        {
            "code": "SWING01",
            "qty": 8,
            "avg_price": 100_000.0,
            "current_price": 110_000,
            "pnl": 80_000,
        }
    ]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
        use_realized_profit_buffer=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 5, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 5

def test_enter_position_returns_sizing_metadata() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "005930"
            assert order_type == "best"
            assert price == 50_000
            return {
                "ord_psbl_cash": 900_000,
                "nrcvb_buy_amt": 900_000,
                "nrcvb_buy_qty": 14,
                "max_buy_qty": 14,
                "psbl_qty_calc_unpr": 50_000,
            }

    api = BuyableAPI()
    api._cash_available = 1_000_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.0}
    state = new_state("20260408")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="S",
        code="005930",
        cash_ratio=0.8,
        asof_date="20260408",
        now=datetime(2026, 4, 8, 9, 10),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 14
    assert result.sizing == {
        "cash_available_snapshot": 1_000_000,
        "sizing_cash": 900_000,
        "quote_price": 50_000.0,
        "sizing_price": 50_000.0,
        "budget_cash": 720_000,
        "max_qty": 14,
        "requested_qty": 14,
        "cash_ratio": 0.8,
        "order_type": "best",
    }

def test_enter_position_best_order_uses_quote_price_before_retrying_down() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "050890"
            assert order_type == "best"
            assert price == 17_430
            return {
                "ord_psbl_cash": 374_960,
                "nrcvb_buy_amt": 374_960,
                "nrcvb_buy_qty": 17,
                "max_buy_qty": 17,
                "psbl_qty_calc_unpr": 21_900,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            if qty >= 11:
                return {"success": False, "msg": "주문가능금액을 초과 했습니다"}
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": self.quote(code).get("price", 0),
            }

    api = BuyableAPI()
    api._cash_available = 378_245
    api._quotes["050890"] = {"price": 17_430, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="050890",
        cash_ratio=1.0,
        budget_cash_cap=200_000,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 10
    assert api.order_calls == [
        {"side": "BUY", "code": "050890", "qty": 11, "order_type": "best", "price": None},
        {"side": "BUY", "code": "050890", "qty": 10, "order_type": "best", "price": None},
    ]
    assert result.sizing == {
        "cash_available_snapshot": 378_245,
        "sizing_cash": 374_960,
        "quote_price": 17_430.0,
        "sizing_price": 17_430.0,
        "budget_cash": 200_000,
        "max_qty": 17,
        "requested_qty": 10,
        "cash_ratio": 1.0,
        "order_type": "best",
    }

def test_enter_position_does_not_initially_cap_order_by_broker_max_qty() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "018880"
            assert order_type == "best"
            assert price == 4_265
            return {
                "ord_psbl_cash": 239_888,
                "nrcvb_buy_amt": 238_694,
                "nrcvb_buy_qty": 44,
                "max_buy_qty": 44,
                "psbl_qty_calc_unpr": 4_265,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": 4_225,
            }

    api = BuyableAPI()
    api._cash_available = 239_888
    api._quotes["018880"] = {"price": 4_265, "change_pct": 1.0}
    state = new_state("20260421")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="018880",
        cash_ratio=0.20,
        budget_cash_cap=214_728,
        asof_date="20260421",
        now=datetime(2026, 4, 21, 9, 16),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 50
    assert api.order_calls == [
        {"side": "BUY", "code": "018880", "qty": 50, "order_type": "best", "price": None}
    ]
    assert result.sizing == {
        "cash_available_snapshot": 239_888,
        "sizing_cash": 238_694,
        "quote_price": 4_265.0,
        "sizing_price": 4_265.0,
        "budget_cash": 214_728,
        "max_qty": 44,
        "requested_qty": 50,
        "cash_ratio": 0.2,
        "order_type": "best",
    }

def test_enter_position_does_not_book_fill_from_order_acceptance_only() -> None:
    class PendingOnlyAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": True, "order_id": f"{side}-{code}", "msg": "주문 접수"}

    api = PendingOnlyAPI()
    api._cash_available = 500_000
    api._quotes["005930"] = {"price": 100_000, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="S",
        code="005930",
        cash_ratio=0.5,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="MKT",
    )

    assert result is None
    assert "005930" not in state.open_positions
    assert state.swing_entries_today == 0

def test_enter_position_limit_order_retries_with_higher_price_after_rejection() -> None:
    class RetryPriceAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            if price == 10_010:
                return {"success": False, "order_id": "BUY-005930-1", "msg": "호가 부적합"}
            return {
                "success": True,
                "order_id": "BUY-005930-2",
                "filled_qty": qty,
                "avg_price": price,
            }

    api = RetryPriceAPI()
    api._cash_available = 500_000
    api._quotes["005930"] = {"price": 10_000, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="005930",
        cash_ratio=0.2,
        budget_cash_cap=200_000,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="limit",
        price=10_010,
    )

    assert result is not None
    assert result.avg_price == 10_020
    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 20, "order_type": "limit", "price": 10_010},
        {"side": "BUY", "code": "005930", "qty": 19, "order_type": "limit", "price": 10_020},
    ]

def test_enter_position_normalizes_invalid_limit_price_to_valid_tick() -> None:
    class NormalizePriceAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-1",
                "filled_qty": qty,
                "avg_price": price,
            }

    api = NormalizePriceAPI()
    api._cash_available = 500_000
    api._quotes["027360"] = {"price": 14_340, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="027360",
        cash_ratio=0.2,
        budget_cash_cap=250_000,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 13, 2),
        order_type="limit",
        price=14_345,
    )

    assert result is not None
    assert result.avg_price == 14_350
    assert api.order_calls == [
        {"side": "BUY", "code": "027360", "qty": 17, "order_type": "limit", "price": 14_350},
    ]

def test_enter_position_fills_missing_limit_price_from_quote() -> None:
    class MissingLimitPriceAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-1",
                "filled_qty": qty,
                "avg_price": price,
            }

    api = MissingLimitPriceAPI()
    api._cash_available = 500_000
    api._quotes["100790"] = {"price": 60_250, "change_pct": 3.5}
    state = new_state("20260423")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="100790",
        cash_ratio=0.2,
        budget_cash_cap=250_000,
        asof_date="20260423",
        now=datetime(2026, 4, 23, 13, 4),
        order_type="limit",
        price=None,
    )

    assert result is not None
    assert result.avg_price == 60_300
    assert api.order_calls == [
        {"side": "BUY", "code": "100790", "qty": 4, "order_type": "limit", "price": 60_300},
    ]

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
                {"order_id": "old-1", "order_time": "090000", "remaining_qty": 3},
                {"order_id": "recent-1", "order_time": "090045", "remaining_qty": 2},
                {"order_id": "filled-1", "order_time": "085900", "remaining_qty": 0, "status": "FILLED"},
                {"order_id": "unknown-1", "remaining_qty": 1},
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
    assert result == {"cancelled": 1, "skipped_recent": 1, "skipped_unknown_time": 1}

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
        "마지막가=127000 주문사유=수익보전 이탈 주문번호=0020845000"
    ]

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
    assert journal_rows == []
    assert notifications == []

def test_save_state_roundtrip_uses_atomic_replace(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state = new_state("20260415")
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
    assert loaded.open_positions["005930"].qty == 5
    assert state_path.read_text(encoding="utf-8").endswith("\n")
