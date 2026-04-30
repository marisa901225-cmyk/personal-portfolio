from .trading_engine_support import *  # noqa: F401,F403
from backend.services.trading_engine.day_chart_review import _candidate_meta_text

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
    assert "추가 비교 후보: PASS01" in paid_message


def test_candidate_meta_text_uses_change_and_liquidity_fallbacks() -> None:
    row = pd.Series(
        {
            "name": "에코프로비엠",
            "avg_value_20d": 210_000_000_000,
        }
    )

    text = _candidate_meta_text(
        rank=5,
        code="247540",
        row=row,
        quote={"price": 211500.0, "change_rate": 4.2},
    )

    assert "후보 5: 에코프로비엠(247540)" in text
    assert "- 현재가: 211500.0" in text
    assert "- 등락률: 4.2%" in text
    assert "- 20일 평균 거래대금: 2100.0억" in text
    assert "- 직전 10일 최고 종가 대비: N/A%" in text

def test_day_chart_review_limits_paid_selection_to_local_approvals_when_reference_added(tmp_path) -> None:
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
                    {"code": "NEXT01", "decision": "ENTER", "reason": "타이밍 양호", "confidence": 0.7},
                ],
            }
        ),
        paid_raw=json.dumps(
            {
                "selected_code": "PASS01",
                "summary": "비교용 후보가 가장 좋아 보임",
                "candidates": [
                    {"code": "PASS01", "decision": "ENTER", "reason": "가장 강함", "confidence": 0.95},
                    {"code": "KEEP01", "decision": "UNSURE", "reason": "무난", "confidence": 0.6},
                    {"code": "NEXT01", "decision": "ENTER", "reason": "후보 유지", "confidence": 0.8},
                ],
            }
        ),
    )

    cfg = TradeEngineConfig(
        output_dir=str(tmp_path / "output"),
        day_chart_review_enabled=True,
        day_chart_review_paid_min_candidates=3,
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
    assert review.selected_code == "KEEP01"
    assert review.approved_codes == ["KEEP01", "NEXT01"]

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
    assert bot.state.open_positions["005930"].locked_profit_pct is None
