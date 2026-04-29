from .trading_engine_support import *  # noqa: F401,F403

from backend.services.trading_engine.day_stop_review import (
    DayOvernightCarryReviewResult,
    DayStopReviewResult,
)

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
