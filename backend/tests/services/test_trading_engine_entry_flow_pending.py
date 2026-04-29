from .trading_engine_support import *  # noqa: F401,F403


def test_day_entry_marks_pending_on_accepted_order_without_open_order_and_stops_retrying_candidates(tmp_path) -> None:
    class AcceptedButLaggingAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": True, "order_id": f"pending-{code}", "msg": "주문 접수"}

    asof = "20260216"
    api = AcceptedButLaggingAPI()
    api._quotes["005935"] = {"price": 158_200, "change_pct": 2.1}
    api._quotes["047040"] = {"price": 35_200, "change_pct": 2.5}

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
        popular=pd.DataFrame([{"code": "005935"}, {"code": "047040"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with (
        patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005935", "047040"]),
        patch(
            "backend.services.trading_engine.bot.review_day_candidates_with_llm",
            return_value=DayChartReviewResult(
                shortlisted_codes=["005935", "047040"],
                approved_codes=["005935", "047040"],
                selected_code="005935",
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

    assert bot.state.pending_entry_orders == {"005935": "T"}
    assert api.order_calls == [
        {"side": "BUY", "code": "005935", "qty": 1, "order_type": "limit", "price": 158_300}
    ]


def test_can_enter_rejects_invalid_entry_type() -> None:
    state = new_state("20260429")
    ok, reason = can_enter(
        "bad",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 4, 29, 9, 10),
        config=TradeEngineConfig(),
        is_trading_day_value=True,
    )

    assert ok is False
    assert reason == "INVALID_ENTRY_TYPE"
