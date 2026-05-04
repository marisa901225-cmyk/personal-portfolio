from .trading_engine_support import *  # noqa: F401,F403

from backend.services.trading_engine.global_market_signal import clear_global_market_signal_cache, get_or_build_global_market_signal
from backend.services.trading_engine.run_context import CachedTradingAPI, TradingRunMetrics


def test_cached_trading_api_reuses_larger_daily_bars_lookback_for_smaller_request() -> None:
    class CountingDailyBarsAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.daily_bars_calls: list[tuple[str, str, int]] = []

        def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
            self.daily_bars_calls.append((code, end, lookback))
            return super().daily_bars(code, end, lookback)

    asof = "20260430"
    api = CountingDailyBarsAPI()
    api._bars[("005930", asof)] = _make_bars(asof, 140, 100.0, 1.0, value=100_000_000_000)
    metrics = TradingRunMetrics()
    cached = CachedTradingAPI(api, metrics=metrics)

    first = cached.daily_bars("005930", asof, 140)
    second = cached.daily_bars("005930", asof, 10)

    assert len(first) == 140
    assert len(second) == 10
    assert api.daily_bars_calls == [("005930", asof, 140)]
    assert metrics.counters["daily_bars_requests"] == 2
    assert metrics.counters["daily_bars_api_calls"] == 1
    assert metrics.counters["daily_bars_cache_hits"] == 1


def test_cached_trading_api_reuses_rank_requests_for_same_cycle() -> None:
    class CountingRankAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.volume_rank_calls: list[tuple[str, int, str]] = []
            self.hts_top_view_calls: list[tuple[int, str]] = []
            self.market_cap_calls: list[tuple[int, str]] = []

        def volume_rank(self, kind: str, top_n: int, asof: str) -> list[dict]:
            self.volume_rank_calls.append((kind, top_n, asof))
            return [
                {"code": f"{kind}-{idx}", "rank": idx}
                for idx in range(1, top_n + 1)
            ]

        def hts_top_view_rank(self, top_n: int, asof: str) -> list[dict]:
            self.hts_top_view_calls.append((top_n, asof))
            return [
                {"code": f"view-{idx}", "rank": idx}
                for idx in range(1, top_n + 1)
            ]

        def market_cap_rank(self, top_k: int, asof: str) -> list[dict]:
            self.market_cap_calls.append((top_k, asof))
            return [
                {"code": f"mcap-{idx}", "rank": idx}
                for idx in range(1, top_k + 1)
            ]

    asof = "20260430"
    api = CountingRankAPI()
    metrics = TradingRunMetrics()
    cached = CachedTradingAPI(api, metrics=metrics)

    first_volume = cached.volume_rank("volume", top_n=100, asof=asof)
    second_volume = cached.volume_rank("volume", top_n=50, asof=asof)
    first_value = cached.volume_rank("value", top_n=80, asof=asof)
    second_value = cached.volume_rank("value", top_n=80, asof=asof)
    first_view = cached.hts_top_view_rank(top_n=20, asof=asof)
    second_view = cached.hts_top_view_rank(top_n=10, asof=asof)
    first_mcap = cached.market_cap_rank(top_k=500, asof=asof)
    second_mcap = cached.market_cap_rank(top_k=200, asof=asof)

    assert len(first_volume) == 100
    assert len(second_volume) == 50
    assert len(first_value) == 80
    assert len(second_value) == 80
    assert len(first_view) == 20
    assert len(second_view) == 10
    assert len(first_mcap) == 500
    assert len(second_mcap) == 200
    assert api.volume_rank_calls == [
        ("volume", 100, asof),
        ("value", 80, asof),
    ]
    assert api.hts_top_view_calls == [(20, asof)]
    assert api.market_cap_calls == [(500, asof)]
    assert metrics.counters["volume_rank_requests"] == 4
    assert metrics.counters["volume_rank_api_calls"] == 2
    assert metrics.counters["volume_rank_cache_hits"] == 2
    assert metrics.counters["hts_top_view_rank_requests"] == 2
    assert metrics.counters["hts_top_view_rank_api_calls"] == 1
    assert metrics.counters["hts_top_view_rank_cache_hits"] == 1
    assert metrics.counters["market_cap_rank_requests"] == 2
    assert metrics.counters["market_cap_rank_api_calls"] == 1
    assert metrics.counters["market_cap_rank_cache_hits"] == 1
    assert cached.snapshot_counts()["volume_rank_cache_entries"] == 2


def test_global_market_signal_is_reused_from_same_day_cache() -> None:
    class CountingGlobalSignalAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.overseas_calls: list[tuple[str, str]] = []

        def overseas_new_highlow_rank(
            self,
            *,
            exchange_code: str,
            high_low_type: str,
            breakout_type: str,
            nday: str,
            volume_rank: str,
        ) -> list[dict[str, object]]:
            self.overseas_calls.append((exchange_code, high_low_type))
            if exchange_code == "NAS" and high_low_type == "1":
                return [
                    {
                        "symb": "NVDA",
                        "name": "엔비디아",
                        "ename": "NVIDIA Corporation",
                        "price": 120.0,
                        "change_pct": 2.3,
                        "volume": 1_500_000,
                        "tradable": "Y",
                    }
                ]
            return []

    clear_global_market_signal_cache()
    api = CountingGlobalSignalAPI()
    cfg = TradeEngineConfig(use_global_market_leadership=True)

    first, first_cache_hit = get_or_build_global_market_signal(api, cfg, trade_date="20260430")
    second, second_cache_hit = get_or_build_global_market_signal(api, cfg, trade_date="20260430")

    assert first is not None
    assert second is not None
    assert first.high_count == 1
    assert second.high_count == 1
    assert first_cache_hit is False
    assert second_cache_hit is True
    assert len(api.overseas_calls) == 6


def test_run_once_reorders_protective_steps_before_candidate_scan(tmp_path) -> None:
    api = FakeAPI()
    asof = "20260430"
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        defer_swing_scan_in_day_entry_window=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    events: list[str] = []
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                with patch(
                    "backend.services.trading_engine.bot.handle_open_orders",
                    side_effect=lambda *args, **kwargs: events.append("handle_open_orders"),
                ):
                    with patch.object(
                        bot,
                        "_reconcile_state_with_broker_positions",
                        side_effect=lambda *args, **kwargs: events.append("reconcile"),
                    ):
                        with patch.object(
                            bot,
                            "_refresh_pending_entry_orders",
                            side_effect=lambda *args, **kwargs: events.append("refresh_entry"),
                        ):
                            with patch.object(
                                bot,
                                "_refresh_pending_exit_orders",
                                side_effect=lambda *args, **kwargs: events.append("refresh_exit"),
                            ):
                                with patch.object(
                                    bot,
                                    "monitor_positions",
                                    side_effect=lambda *args, **kwargs: events.append("monitor"),
                                ):
                                    with patch(
                                        "backend.services.trading_engine.bot.build_day_candidates",
                                        side_effect=lambda *args, **kwargs: events.append("build_day") or empty_candidates,
                                    ):
                                        out = bot.run_once(now=datetime(2026, 4, 30, 9, 10))

    assert out["status"] == "OK"
    assert events[:6] == [
        "handle_open_orders",
        "reconcile",
        "refresh_entry",
        "refresh_exit",
        "monitor",
        "build_day",
    ]


def test_run_once_dedupes_intraday_confirmation_and_journal(tmp_path) -> None:
    class CountingIntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.intraday_calls: list[tuple[str, str, int]] = []

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            self.intraday_calls.append((code, asof, lookback))
            return _make_intraday_bars(asof, [100.0, 99.0, 98.0], last_change_pct=-2.0)

    asof = "20260430"
    api = CountingIntradayAPI()
    api._quotes["DAY1"] = {"price": 98_000, "change_pct": -2.0}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        day_chart_review_enabled=False,
        swing_chart_review_enabled=False,
        defer_swing_scan_in_day_entry_window=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    day_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "DAY1", "name": "Day One"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame([{"code": "DAY1", "name": "Day One"}]),
        quote_codes=["DAY1"],
    )
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                with patch("backend.services.trading_engine.bot.build_day_candidates", return_value=day_candidates):
                    with patch("backend.services.trading_engine.bot.build_swing_candidates", return_value=empty_candidates):
                        with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["DAY1", "DAY1"]):
                            out = bot.run_once(now=datetime(2026, 4, 30, 9, 10))

    assert out["status"] == "OK"
    assert api.intraday_calls == [("DAY1", asof, 12)]

    journal_path = tmp_path / "output" / f"trade_journal_{asof}.jsonl"
    rows = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    filtered = [row for row in rows if row.get("event") == "DAY_CANDIDATE_FILTERED"]
    assert len(filtered) == 1
    assert filtered[0]["code"] == "DAY1"


def test_run_once_skips_swing_scan_in_first_day_window_when_enabled(tmp_path) -> None:
    api = FakeAPI()
    asof = "20260430"
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        defer_swing_scan_in_day_entry_window=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                with patch("backend.services.trading_engine.bot.build_day_candidates", return_value=empty_candidates):
                    with patch(
                        "backend.services.trading_engine.bot.build_swing_candidates",
                        side_effect=AssertionError("swing scan should be deferred"),
                    ):
                        out = bot.run_once(now=datetime(2026, 4, 30, 9, 10))

    assert out["status"] == "OK"
