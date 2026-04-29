from .trading_engine_support import *  # noqa: F401,F403
from backend.services.trading_engine.day_chart_review import _candidate_meta_text

def test_day_pending_order_consumes_total_slot_until_resolved(tmp_path) -> None:
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
                    "order_id": f"pending-{code}",
                    "code": code,
                    "side": "buy",
                    "qty": qty,
                    "price": price,
                    "remaining_qty": qty,
                }
            ]
            return {"success": True, "order_id": f"pending-{code}", "msg": "주문 접수"}

        def open_orders(self) -> list[dict]:
            return list(self._open_orders)

    asof = "20260216"
    api = PendingOrderAPI()
    api._quotes["005935"] = {"price": 158_200, "change_pct": 2.1}
    api._quotes["047040"] = {"price": 35_200, "change_pct": 2.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        max_total_positions=1,
        max_day_positions=1,
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=False,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        day_chart_review_enabled=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof

    first_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "005935"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )
    second_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "047040"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch("backend.services.trading_engine.bot.rank_daytrade_codes", side_effect=[["005935"], ["047040"]]),
        patch(
            "backend.services.trading_engine.bot.review_day_candidates_with_llm",
            side_effect=[
                DayChartReviewResult(
                    shortlisted_codes=["005935"],
                    approved_codes=["005935"],
                    selected_code="005935",
                    summary="ENTER",
                    chart_paths=[],
                    raw_response={},
                ),
                DayChartReviewResult(
                    shortlisted_codes=["047040"],
                    approved_codes=["047040"],
                    selected_code="047040",
                    summary="ENTER",
                    chart_paths=[],
                    raw_response={},
                ),
            ],
        ),
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 8),
            regime="RISK_ON",
            candidates=first_candidates,
            quotes=api._quotes,
            news_signal=None,
        )
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=second_candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.pending_entry_orders == {"005935": "T"}
    assert bot.state.pass_reasons_today.get("MAX_DAY_POSITIONS", 0) == 1
    assert api.order_calls == [
        {"side": "BUY", "code": "005935", "qty": 1, "order_type": "limit", "price": 158_300}
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
    assert "222080" not in bot.state.open_positions
    assert bot.state.pending_entry_orders == {"222080": "T"}

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
