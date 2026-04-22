from .trading_engine_support import *  # noqa: F401,F403

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
    assert api.order_calls == [
        {"side": "BUY", "code": "222080", "qty": 20, "order_type": "limit", "price": 10_010}
    ]

def test_day_entry_syncs_broker_position_before_reporting_failure(tmp_path) -> None:
    class DelayedFillAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.position_reads = 0

        def positions(self) -> list[dict]:
            self.position_reads += 1
            if self.position_reads >= 3:
                return [{"code": "222080", "qty": 20, "avg_price": 10_010.0}]
            return []

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": True, "order_id": "delayed-222080", "msg": "주문 접수"}

    asof = "20260216"
    api = DelayedFillAPI()
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
    assert "222080" in bot.state.open_positions
    assert bot.state.open_positions["222080"].qty == 20

def test_day_entry_skips_chart_review_after_no_new_entry_cutoff(tmp_path) -> None:
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
        no_new_entry_after="15:00",
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
            now=datetime(2026, 2, 16, 15, 1),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    review_mock.assert_not_called()
    assert bot.state.pass_reasons_today["NO_NEW_ENTRY_AFTER"] == 1

def test_swing_entry_skips_chart_review_when_entry_window_closed(tmp_path) -> None:
    asof = "20260216"
    api = FakeAPI()
    api._quotes["SWING01"] = {"price": 10_000, "change_pct": 2.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        swing_chart_review_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame([{"code": "SWING01"}]),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=["SWING01"]),
        patch("backend.services.trading_engine.bot.review_swing_candidates_with_llm") as review_mock,
    ):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 11, 1),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    review_mock.assert_not_called()
    assert bot.state.pass_reasons_today["ENTRY_WINDOW_CLOSED"] == 1

def test_swing_entry_skips_chart_review_after_no_new_entry_cutoff(tmp_path) -> None:
    asof = "20260216"
    api = FakeAPI()
    api._quotes["SWING01"] = {"price": 10_000, "change_pct": 2.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        swing_chart_review_enabled=True,
        no_new_entry_after="15:00",
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame([{"code": "SWING01"}]),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=["SWING01"]),
        patch("backend.services.trading_engine.bot.review_swing_candidates_with_llm") as review_mock,
    ):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 15, 1),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    review_mock.assert_not_called()
    assert bot.state.pass_reasons_today["NO_NEW_ENTRY_AFTER"] == 1

def test_day_chart_review_uses_paid_tiebreak_after_local_filter(tmp_path) -> None:
    asof = "20260216"

    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    for code, close in (("PASS01", 100.0), ("KEEP01", 110.0), ("NEXT01", 115.0)):
        api._bars[(code, asof)] = _make_bars(asof, 40, close - 10.0, 0.3, value=50_000_000_000)
        api._intraday[(code, asof)] = _make_intraday_bars(asof, [close - 1.0, close, close + 1.0])
        api._quotes[code] = {"price": close, "change_pct": 2.0}

    stub = _ChartReviewLLMStub(
        local_raw=json.dumps(
            {
                "selected_code": "KEEP01",
                "summary": "로컬은 KEEP01 우선",
                "candidates": [
                    {"code": "PASS01", "decision": "PASS", "reason": "과열", "confidence": 0.9},
                    {"code": "KEEP01", "decision": "ENTER", "reason": "안정", "confidence": 0.8},
                    {"code": "NEXT01", "decision": "UNSURE", "reason": "애매", "confidence": 0.6},
                ],
            }
        ),
        paid_raw=json.dumps(
            {
                "selected_code": "NEXT01",
                "summary": "유료는 NEXT01이 더 낫다고 판단",
                "candidates": [
                    {"code": "KEEP01", "decision": "UNSURE", "reason": "무난", "confidence": 0.7},
                    {"code": "NEXT01", "decision": "ENTER", "reason": "더 좋은 타이밍", "confidence": 0.9},
                ],
            }
        ),
    )

    cfg = TradeEngineConfig(
        output_dir=str(tmp_path / "output"),
        day_chart_review_enabled=True,
    )
    candidates = _make_chart_review_candidates(asof)

    with patch("backend.services.trading_engine.day_chart_review.LLMService.get_instance", return_value=stub):
        review = review_day_candidates_with_llm(
            api=api,
            trade_date=asof,
            ranked_codes=["PASS01", "KEEP01", "NEXT01"],
            candidates=candidates,
            quotes=api._quotes,
            config=cfg,
            output_dir=str(tmp_path / "output"),
        )

    assert review is not None
    assert review.shortlisted_codes == ["PASS01", "KEEP01", "NEXT01"]
    assert review.selected_code == "NEXT01"
    assert review.approved_codes == ["NEXT01", "KEEP01"]
    assert stub.local_calls
    assert len(stub.paid_calls) == 1
    paid_message = stub.paid_calls[0]["messages"][1]["content"][0]["text"]
    assert "로컬 1차 검토 통과 후보: KEEP01,NEXT01" in paid_message

def test_day_chart_review_adds_chart_wildcard_candidate_beyond_rank_limit(tmp_path) -> None:
    asof = "20260216"

    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    quotes = {
        "PASS01": {"price": 100.0, "open": 99.0, "high": 100.0, "low": 98.0, "change_pct": 2.0},
        "KEEP01": {"price": 103.0, "open": 101.0, "high": 104.0, "low": 100.0, "change_pct": 2.0},
        "NEXT01": {"price": 100.0, "open": 100.0, "high": 101.0, "low": 99.0, "change_pct": 2.0},
        "WILD01": {"price": 104.0, "open": 100.0, "high": 105.0, "low": 99.0, "change_pct": 2.0},
    }
    for code, quote in quotes.items():
        api._quotes[code] = quote
        api._bars[(code, asof)] = _make_bars(asof, 40, float(quote["price"]) - 10.0, 0.3, value=50_000_000_000)
        api._intraday[(code, asof)] = _make_intraday_bars(
            asof,
            [float(quote["open"]), float(quote["price"]) - 0.5, float(quote["price"])],
        )

    stub = _ChartReviewLLMStub(
        local_raw=json.dumps(
            {
                "selected_code": "WILD01",
                "summary": "와일드카드 차트가 가장 강함",
                "candidates": [
                    {"code": "PASS01", "decision": "PASS", "reason": "무난", "confidence": 0.6},
                    {"code": "KEEP01", "decision": "UNSURE", "reason": "보통", "confidence": 0.6},
                    {"code": "WILD01", "decision": "ENTER", "reason": "차트 탄력 우수", "confidence": 0.9},
                ],
            }
        ),
        paid_raw="",
        paid_configured=False,
    )

    cfg = TradeEngineConfig(
        output_dir=str(tmp_path / "output"),
        day_chart_review_enabled=True,
        day_chart_review_top_n=2,
        day_chart_review_chart_wildcard_slots=1,
    )
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "PASS01", "name": "Pass 01"},
                {"code": "KEEP01", "name": "Keep 01"},
                {"code": "NEXT01", "name": "Next 01"},
                {"code": "WILD01", "name": "Wild 01"},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.day_chart_review.LLMService.get_instance", return_value=stub):
        review = review_day_candidates_with_llm(
            api=api,
            trade_date=asof,
            ranked_codes=["PASS01", "KEEP01", "NEXT01", "WILD01"],
            candidates=candidates,
            quotes=api._quotes,
            config=cfg,
            output_dir=str(tmp_path / "output"),
        )

    assert review is not None
    assert review.shortlisted_codes == ["PASS01", "KEEP01", "WILD01"]
    assert review.selected_code == "WILD01"
    assert review.approved_codes == ["WILD01", "KEEP01"]
    assert len(stub.local_calls) == 1
    assert len(stub.paid_calls) == 0

def test_day_chart_review_falls_back_to_paid_when_local_parse_fails(tmp_path) -> None:
    asof = "20260216"

    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    for code, close in (("PASS01", 100.0), ("KEEP01", 110.0)):
        api._bars[(code, asof)] = _make_bars(asof, 40, close - 10.0, 0.3, value=50_000_000_000)
        api._intraday[(code, asof)] = _make_intraday_bars(asof, [close - 1.0, close, close + 1.0])
        api._quotes[code] = {"price": close, "change_pct": 2.0}

    stub = _ChartReviewLLMStub(
        local_raw="this is not json",
        paid_raw=json.dumps(
            {
                "selected_code": "KEEP01",
                "summary": "유료만 성공",
                "candidates": [
                    {"code": "PASS01", "decision": "PASS", "reason": "과열", "confidence": 0.9},
                    {"code": "KEEP01", "decision": "ENTER", "reason": "무난", "confidence": 0.8},
                ],
            }
        ),
    )

    cfg = TradeEngineConfig(
        output_dir=str(tmp_path / "output"),
        day_chart_review_enabled=True,
    )
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "PASS01", "name": "Pass 01"}, {"code": "KEEP01", "name": "Keep 01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.day_chart_review.LLMService.get_instance", return_value=stub):
        review = review_day_candidates_with_llm(
            api=api,
            trade_date=asof,
            ranked_codes=["PASS01", "KEEP01"],
            candidates=candidates,
            quotes=api._quotes,
            config=cfg,
            output_dir=str(tmp_path / "output"),
        )

    assert review is not None
    assert review.selected_code == "KEEP01"
    assert review.approved_codes == ["KEEP01"]
    assert len(stub.local_calls) == 1
    assert len(stub.paid_calls) == 1

def test_day_entry_records_veto_when_chart_review_rejects_all(tmp_path) -> None:
    asof = "20260216"
    api = FakeAPI()
    api._quotes["PASS01"] = {"price": 10_000, "change_pct": 2.1}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.8}

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
        popular=pd.DataFrame([{"code": "PASS01"}, {"code": "KEEP01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch(
            "backend.services.trading_engine.bot.rank_daytrade_codes",
            return_value=["PASS01", "KEEP01"],
        ),
        patch(
            "backend.services.trading_engine.bot.review_day_candidates_with_llm",
            return_value=DayChartReviewResult(
                shortlisted_codes=["PASS01", "KEEP01"],
                approved_codes=[],
                selected_code=None,
                summary="둘 다 추격 위험",
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

    assert api.order_calls == []
    assert bot.state.pass_reasons_today["DAY_LLM_VETO"] == 1

def test_bot_holds_profitable_broker_position_when_same_symbol_is_picked(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.5}
    api._positions = [
        {"code": "005930", "qty": 3, "avg_price": 100_000.0, "current_price": 105_000, "pnl": 15_000}
    ]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": "800000000000",
                    "ma20": 102_000,
                    "ma60": 99_000,
                    "close": 105_000,
                    "change_pct": "1.5",
                    "is_etf": False,
                    "trend_tier": "strict",
                }
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_20d": "800000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == []
    assert "005930" in bot.state.open_positions
    assert bot.state.open_positions["005930"].type == "S"
    assert abs(float(bot.state.open_positions["005930"].locked_profit_pct or 0.0) - 0.05) < 1e-9

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
