from .trading_engine_support import *  # noqa: F401,F403
from backend.services.trading_engine.day_chart_review import _candidate_meta_text

def test_swing_stop_loss_requires_trend_break(tmp_path) -> None:
    code = "111111"
    asof = "20260216"
    now = datetime(2026, 2, 16, 10, 0)

    api = FakeAPI()
    api._quotes[code] = {"price": 96, "change_pct": -4.0}
    api._bars[(code, asof)] = pd.DataFrame(
        [
            {"date": "20260212", "close": 90, "volume": 1_000_000},
            {"date": "20260213", "close": 95, "volume": 1_000_000},
            {"date": "20260214", "close": 100, "volume": 1_000_000},
        ]
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_stop_loss_pct=-0.03,
        swing_sl_requires_trend_break=True,
        swing_trend_ma_window=3,
        swing_trend_lookback_bars=5,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.open_positions[code] = PositionState(
        type="S",
        entry_time="2026-02-14T09:10:00",
        entry_price=100.0,
        qty=10,
        highest_price=102.0,
        entry_date="20260214",
        bars_held=1,
    )

    # 손실률은 -4%지만, MA(=95) 위이므로 추세 훼손 아님 -> 즉시 손절 금지
    bot.monitor_positions(now=now)
    assert api.order_calls == []
    assert code in bot.state.open_positions

    # 동일 손실률에서 MA를 상회하지 못하게 만들어 추세 훼손 유도 -> 손절 실행
    api._bars[(code, asof)] = pd.DataFrame(
        [
            {"date": "20260212", "close": 110, "volume": 1_000_000},
            {"date": "20260213", "close": 108, "volume": 1_000_000},
            {"date": "20260214", "close": 106, "volume": 1_000_000},
        ]
    )
    bot.monitor_positions(now=now)

    assert any(call["side"] == "SELL" and call["code"] == code for call in api.order_calls)
    assert code not in bot.state.open_positions

def test_detect_intraday_cb_day_change_drop() -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    asof = "20260304"
    code = "069500"
    api._intraday[(code, asof)] = _make_intraday_bars(asof, [100.0, 99.9, 99.8], last_change_pct=-3.5)

    triggered, meta = detect_intraday_circuit_breaker(
        api,
        asof=asof,
        code=code,
        one_bar_drop_pct=-10.0,
        window_minutes=5,
        window_drop_pct=-10.0,
        day_change_pct=-3.0,
    )

    assert triggered is True
    assert meta.get("reason") == "DAY_CHANGE_DROP"

def test_detect_intraday_cb_last_bar_drop() -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    asof = "20260304"
    code = "069500"
    api._intraday[(code, asof)] = _make_intraday_bars(asof, [100.0, 100.3, 98.9])

    triggered, meta = detect_intraday_circuit_breaker(
        api,
        asof=asof,
        code=code,
        one_bar_drop_pct=-1.0,
        window_minutes=5,
        window_drop_pct=-10.0,
        day_change_pct=-10.0,
    )

    assert triggered is True
    assert meta.get("reason") == "INTRADAY_BAR_DROP"

def test_get_regime_reports_actual_recent_panic_date() -> None:
    asof = "20260312"
    api = FakeAPI()
    closes = [float(100 + idx) for idx in range(77)] + [166.0, 168.0, 170.0]
    api._bars[("069500", asof)] = _make_bars_from_closes(asof, closes)

    regime, panic_date = get_regime(api, asof)

    assert regime == "RISK_OFF"
    assert panic_date == "20260310"

def test_get_regime_uses_relaxed_default_vol_threshold_for_war_volatility() -> None:
    asof = "20260316"
    api = FakeAPI()
    closes = [100 + i for i in range(60)] + [
        160.0, 166.0, 161.0, 168.0, 162.0,
        170.0, 165.0, 172.0, 168.0, 174.0,
        171.0, 176.0, 170.0, 178.0, 173.0,
        180.0, 176.0, 182.0, 179.0, 184.0,
    ]
    api._bars[("069500", asof)] = _make_bars_from_closes(asof, closes)

    relaxed_regime, relaxed_panic_date = get_regime(api, asof)
    strict_regime, strict_panic_date = get_regime(api, asof, vol_threshold=0.03)

    assert relaxed_regime == "RISK_ON"
    assert relaxed_panic_date is None
    assert strict_regime == "RISK_OFF"
    assert strict_panic_date is None

def test_bot_keeps_original_panic_date_inside_recent_window(tmp_path) -> None:
    asof = "20260312"
    api = FakeAPI()
    closes = [float(100 + idx) for idx in range(77)] + [166.0, 168.0, 170.0]
    api._bars[("069500", asof)] = _make_bars_from_closes(asof, closes)

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.last_panic_date = "20260310"

    out = bot.run_once(now=datetime(2026, 3, 12, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert bot.state.last_panic_date == "20260310"

def test_bot_intraday_cb_forces_risk_off(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260304"
    api = IntradayAPI()
    api._bars[("069500", asof)] = _make_bars(asof, 80, 100.0, 1.0)
    api._intraday[("069500", asof)] = _make_intraday_bars(asof, [100.0, 100.4, 98.8])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    out = bot.run_once(now=datetime(2026, 3, 4, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert bot.state.last_panic_date == asof
    assert int(bot.state.pass_reasons_today.get("RISK_OFF", 0)) >= 1

def test_runtime_loads_position_limit_overrides_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "TRADING_ENGINE_MAX_SWING_POSITIONS": "2",
            "TRADING_ENGINE_MAX_DAY_POSITIONS": "2",
            "TRADING_ENGINE_MAX_TOTAL_POSITIONS": "3",
            "TRADING_ENGINE_MAX_SWING_ENTRIES_PER_WEEK": "4",
            "TRADING_ENGINE_MAX_SWING_ENTRIES_PER_DAY": "2",
            "TRADING_ENGINE_MAX_DAY_ENTRIES_PER_DAY": "2",
            "TRADING_ENGINE_DAY_CONDITIONAL_EXTRA_ENTRIES_ENABLED": "1",
            "TRADING_ENGINE_DAY_CONDITIONAL_EXTRA_ENTRIES": "3",
            "TRADING_ENGINE_DAY_CONDITIONAL_EXTRA_MIN_CLOSED_TRADES": "4",
            "TRADING_ENGINE_DAY_CONDITIONAL_EXTRA_MIN_WIN_RATE": "0.7",
            "TRADING_ENGINE_DAY_CONDITIONAL_EXTRA_MIN_REALIZED_PNL": "5000",
            "TRADING_ENGINE_DAY_CONDITIONAL_EXTRA_MAX_CONSECUTIVE_LOSSES": "1",
            "TRADING_ENGINE_DAY_AFTERNOON_ENTRY_START_WINDOW_INDEX": "3",
            "TRADING_ENGINE_DAY_AFTERNOON_LOSS_LIMIT_LOSS_COUNT": "1",
            "TRADING_ENGINE_DAY_STOPLOSS_EXCLUDE_AFTER_LOSSES": "3",
            "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MIN_DAY_CHANGE_PCT": "1.4",
            "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MIN_WINDOW_CHANGE_PCT": "0.08",
            "TRADING_ENGINE_DAY_MOMENTUM_CHASE_MAX_CHANGE_PCT": "24.0",
            "TRADING_ENGINE_DAY_MOMENTUM_PULLBACK_MIN_DAY_CHANGE_PCT": "10.0",
            "TRADING_ENGINE_DAY_THEME_CANDIDATE_MAX_INJECTIONS": "4",
            "TRADING_ENGINE_DAY_THEME_CANDIDATE_MIN_SECTOR_SCORE": "0.45",
            "TRADING_ENGINE_USE_REALIZED_PROFIT_BUFFER": "0",
            "TRADING_ENGINE_SWING_PREFER_SECTOR_ETF_ON_THEME_DAY": "1",
            "TRADING_ENGINE_SWING_SECTOR_ETF_MIN_BREADTH": "3",
        },
        clear=False,
    ):
        cfg = _load_config_from_env()

    assert cfg.max_swing_positions == 2
    assert cfg.max_day_positions == 2
    assert cfg.max_total_positions == 3
    assert cfg.max_swing_entries_per_week == 4
    assert cfg.max_swing_entries_per_day == 2
    assert cfg.max_day_entries_per_day == 2
    assert cfg.day_conditional_extra_entries_enabled is True
    assert cfg.day_conditional_extra_entries == 3
    assert cfg.day_conditional_extra_min_closed_trades == 4
    assert cfg.day_conditional_extra_min_win_rate == 0.7
    assert cfg.day_conditional_extra_min_realized_pnl == 5000
    assert cfg.day_conditional_extra_max_consecutive_losses == 1
    assert cfg.day_afternoon_entry_start_window_index == 3
    assert cfg.day_afternoon_loss_limit_loss_count == 1
    assert cfg.day_stoploss_exclude_after_losses == 3
    assert cfg.day_intraday_tight_base_min_day_change_pct == 1.4
    assert cfg.day_intraday_tight_base_min_window_change_pct == 0.08
    assert cfg.day_momentum_chase_max_change_pct == 24.0
    assert cfg.day_momentum_pullback_min_day_change_pct == 10.0
    assert cfg.day_theme_candidate_max_injections == 4
    assert cfg.day_theme_candidate_min_sector_score == 0.45
    assert cfg.use_realized_profit_buffer is False
    assert cfg.swing_prefer_sector_etf_on_theme_day is True
    assert cfg.swing_sector_etf_min_breadth == 3
