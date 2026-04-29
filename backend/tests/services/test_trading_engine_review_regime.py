from .trading_engine_support import *  # noqa: F401,F403
from backend.services.trading_engine.day_chart_review import _candidate_meta_text

def test_day_entry_falls_back_to_next_affordable_candidate(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["EXPENSIVE"] = {"price": 300_000, "change_pct": 6.0}
    api._quotes["AFFORD01"] = {"price": 10_000, "change_pct": 5.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
    )
    bot = HybridTradingBot(api, config=cfg)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame([{"code": "EXPENSIVE"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["EXPENSIVE", "AFFORD01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "AFFORD01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "AFFORD01", "qty": 20, "order_type": "limit", "price": 10_010}
    ]

def test_day_entry_reopens_in_afternoon_after_morning_round_trip(tmp_path) -> None:
    asof = "20260216"
    api = FakeAPI()
    api._quotes["MORN01"] = {"price": 10_000, "change_pct": 4.0}
    api._quotes["AFTER01"] = {"price": 10_000, "change_pct": 3.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "MORN01"}, {"code": "AFTER01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["MORN01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    first_exit = exit_position(
        api,
        bot.state,
        code="MORN01",
        reason="TP",
        now=datetime(2026, 2, 16, 9, 35),
        config=cfg,
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["AFTER01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert first_exit is not None
    assert bot.state.day_entries_today == 2
    assert "MORN01" not in bot.state.open_positions
    assert "AFTER01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "MORN01", "qty": 20, "order_type": "limit", "price": 10_010},
        {"side": "SELL", "code": "MORN01", "qty": 20, "order_type": "MKT", "price": None},
        {"side": "BUY", "code": "AFTER01", "qty": 20, "order_type": "limit", "price": 10_010},
    ]

def test_day_entry_skips_fading_intraday_candidate_and_uses_next_symbol(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["FADE01"] = {"price": 10_000, "change_pct": 2.0}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.4}
    api._intraday[("FADE01", asof)] = _make_intraday_bars(asof, [100.0, 102.0, 100.8])
    api._intraday[("KEEP01", asof)] = _make_intraday_bars(asof, [100.0, 100.3, 100.7])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        day_chart_review_enabled=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "FADE01"}, {"code": "KEEP01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["FADE01", "KEEP01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "KEEP01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "KEEP01", "qty": 20, "order_type": "limit", "price": 10_010}
    ]

def test_day_entry_skips_candidate_when_intraday_fetch_fails(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            if code == "FAIL01":
                raise RuntimeError("transient broker error")
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["FAIL01"] = {"price": 10_000, "change_pct": 2.4}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.4}
    api._intraday[("KEEP01", asof)] = _make_intraday_bars(asof, [100.0, 100.3, 100.7])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        day_chart_review_enabled=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "FAIL01"}, {"code": "KEEP01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["FAIL01", "KEEP01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "FAIL01" not in bot.state.open_positions
    assert "KEEP01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "KEEP01", "qty": 20, "order_type": "limit", "price": 10_010}
    ]

def test_day_entry_skips_candidate_when_intraday_data_is_missing(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["EMPTY01"] = {"price": 10_000, "change_pct": 2.1}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.4}
    api._intraday[("KEEP01", asof)] = _make_intraday_bars(asof, [100.0, 100.3, 100.7])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        day_chart_review_enabled=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "EMPTY01"}, {"code": "KEEP01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["EMPTY01", "KEEP01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "EMPTY01" not in bot.state.open_positions
    assert "KEEP01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "KEEP01", "qty": 20, "order_type": "limit", "price": 10_010}
    ]

def test_day_entry_accepts_tight_base_intraday_candidate(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["BASE01"] = {"price": 10_000, "change_pct": 1.8}
    api._quotes["NEXT01"] = {"price": 10_000, "change_pct": 1.2}
    api._intraday[("BASE01", asof)] = _make_intraday_bars(
        asof,
        [100.0, 100.12, 100.18],
        last_change_pct=1.8,
    )
    api._intraday[("NEXT01", asof)] = _make_intraday_bars(
        asof,
        [100.0, 100.3, 100.7],
        last_change_pct=1.2,
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        day_chart_review_enabled=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "BASE01"}, {"code": "NEXT01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["BASE01", "NEXT01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "BASE01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "BASE01", "qty": 20, "order_type": "limit", "price": 10_010}
    ]

def test_day_entry_uses_chart_review_selected_candidate(tmp_path) -> None:
    asof = "20260216"
    api = FakeAPI()
    api._quotes["PASS01"] = {"price": 10_000, "change_pct": 2.1}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.8}
    api._quotes["NEXT01"] = {"price": 10_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        day_chart_review_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "PASS01"}, {"code": "KEEP01"}, {"code": "NEXT01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch(
            "backend.services.trading_engine.bot.rank_daytrade_codes",
            return_value=["PASS01", "KEEP01", "NEXT01"],
        ),
        patch(
            "backend.services.trading_engine.bot.review_day_candidates_with_llm",
            return_value=DayChartReviewResult(
                shortlisted_codes=["PASS01", "KEEP01", "NEXT01"],
                approved_codes=["KEEP01", "NEXT01"],
                selected_code="KEEP01",
                summary="KEEP01이 더 안정적",
                chart_paths=[],
                raw_response={},
            ),
        ),
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "KEEP01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "KEEP01", "qty": 20, "order_type": "limit", "price": 10_010}
    ]

def test_day_entry_skips_chart_review_when_entry_window_closed(tmp_path) -> None:
    asof = "20260216"
    api = FakeAPI()
    api._quotes["PASS01"] = {"price": 10_000, "change_pct": 2.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        day_chart_review_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "PASS01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["PASS01"]),
        patch("backend.services.trading_engine.bot.review_day_candidates_with_llm") as review_mock,
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 11, 1),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    review_mock.assert_not_called()
    assert bot.state.pass_reasons_today["ENTRY_WINDOW_CLOSED"] == 1

def test_day_entry_checks_pending_order_before_reporting_failure(tmp_path) -> None:
    class PendingOrderAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._open_orders: list[dict] = []

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            self._open_orders = [
                {
                    "order_id": "pending-222080",
                    "code": code,
                    "side": "buy",
                    "qty": qty,
                    "price": price,
                    "remaining_qty": qty,
                }
            ]
            return {"success": True, "order_id": "pending-222080", "msg": "주문 접수"}

        def open_orders(self) -> list[dict]:
            return list(self._open_orders)

    asof = "20260216"
    api = PendingOrderAPI()
    api._quotes["222080"] = {"price": 10_000, "change_pct": 2.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        day_chart_review_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "222080"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["222080"]),
        patch(
            "backend.services.trading_engine.bot.review_day_candidates_with_llm",
            return_value=DayChartReviewResult(
                shortlisted_codes=["222080"],
                approved_codes=["222080"],
                selected_code="222080",
                summary="ENTER",
                chart_paths=[],
                raw_response={},
            ),
        ),
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.pass_reasons_today.get("DAY_ENTRY_FAILED", 0) == 0
    assert "222080" not in bot.state.open_positions
    assert bot.state.pending_entry_orders == {"222080": "T"}
    assert api.order_calls == [
        {"side": "BUY", "code": "222080", "qty": 20, "order_type": "limit", "price": 10_010}
    ]


