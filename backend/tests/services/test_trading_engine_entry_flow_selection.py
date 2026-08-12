from .trading_engine_support import *  # noqa: F401,F403

def test_swing_skip_notification_suppressed_when_swing_position_already_open(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"
    bot.state.open_positions["379800"] = PositionState(
        type="S",
        entry_time="2026-02-16T13:00:00",
        entry_price=23_475.0,
        qty=33,
        highest_price=23_475.0,
        entry_date="20260216",
    )

    empty_candidates = SimpleNamespace(
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
    )

    bot._try_enter_swing(
        now=datetime(2026, 2, 16, 13, 8),
        regime="RISK_ON",
        candidates=empty_candidates,
        quotes={},
    )

    assert bot.state.pass_reasons_today.get("NO_CANDIDATE") == 1
    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[스윙][보류]")]
    assert swing_skip_msgs == []

def test_swing_skip_message_uses_local_llm_rewrite_when_available(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "스윙 후보가 안 보여서 이번 창은 쉬어갔어. 13시에 다시 볼게!"
                        }
                    }
                ]
            }

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"

    empty_candidates = SimpleNamespace(
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.candidate_notifications.load_prompt", return_value="test prompt"):
        with patch.dict(
            "os.environ",
            {
                "LLM_BASE_URL": "http://openvino-server:8082",
                "LLM_TIMEOUT": "4",
                "LLM_REMOTE_DEFAULT_MODEL": "Josiefied-Qwen3-8B-int8",
            },
            clear=False,
        ):
            with patch("backend.services.trading_engine.candidate_notifications.requests.post", return_value=FakeResponse()) as post_mock:
                bot._try_enter_swing(
                    now=datetime(2026, 2, 16, 9, 10),
                    regime="RISK_ON",
                    candidates=empty_candidates,
                    quotes={},
                )

    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[스윙][보류]")]
    assert swing_skip_msgs == ["[스윙][보류] 스윙 후보가 안 보여서 이번 창은 쉬어갔어. 13시에 다시 볼게!"]
    assert post_mock.call_count == 1
    request_payload = post_mock.call_args.kwargs["json"]
    assert request_payload["model"] == "Josiefied-Qwen3-8B-int8"
    assert request_payload["chat_template_kwargs"]["enable_thinking"] is False

def test_swing_lunch_retry_still_respects_existing_position_limit() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:10:00",
        entry_price=100_000.0,
        qty=7,
        highest_price=100_000.0,
        entry_date="20260216",
    )

    ok, reason = can_enter(
        "S",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    assert ok is False
    assert reason == "MAX_SWING_POSITIONS"

def test_swing_hold_skips_rebuy_when_same_symbol_is_already_profitable(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.2}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    bot.state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:10:00",
        entry_price=100_000.0,
        qty=7,
        highest_price=105_000.0,
        entry_date="20260216",
    )

    candidates = SimpleNamespace(
        model=pd.DataFrame([{"code": "005930", "name": "삼성전자"}]),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=["005930"]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
        )

    assert api.order_calls == []
    assert bot.state.pass_reasons_today == {}
    assert bot.state.open_positions["005930"].qty == 7
    assert bot.state.open_positions["005930"].locked_profit_pct is None

def test_swing_entry_falls_back_to_next_candidate_when_top_pick_is_too_expensive(tmp_path) -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert order_type == "limit"
            assert price is not None
            if code == "EXPENSIVE":
                return {
                    "ord_psbl_cash": 200_000,
                    "nrcvb_buy_amt": 200_000,
                    "nrcvb_buy_qty": 0,
                    "max_buy_qty": 0,
                    "psbl_qty_calc_unpr": price,
                }
            return {
                "ord_psbl_cash": 200_000,
                "nrcvb_buy_amt": 200_000,
                "nrcvb_buy_qty": 10,
                "max_buy_qty": 10,
                "psbl_qty_calc_unpr": price,
            }

    api = BuyableAPI()
    api._cash_available = 200_000
    api._quotes["EXPENSIVE"] = {"price": 300_000, "change_pct": 2.0}
    api._quotes["CHEAP"] = {"price": 20_000, "change_pct": 1.5}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_entry_order_type="best",
        swing_chart_review_enabled=False,
        swing_cash_ratio=1.0,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"

    candidates = SimpleNamespace(
        model=pd.DataFrame(
            [
                {"code": "EXPENSIVE", "name": "비싼종목"},
                {"code": "CHEAP", "name": "싼종목"},
            ]
        ),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=["EXPENSIVE", "CHEAP"]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={
                "EXPENSIVE": api.quote("EXPENSIVE"),
                "CHEAP": api.quote("CHEAP"),
            },
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "CHEAP", "qty": 9, "order_type": "limit", "price": 20_050}
    ]
    assert "CHEAP" in bot.state.open_positions
    assert "EXPENSIVE" not in bot.state.open_positions
    assert bot.state.pass_reasons_today == {}

def test_swing_entry_sweeps_same_sector_peer_when_top_and_second_pick_fail_budget(tmp_path) -> None:
    api = FakeAPI()
    api._cash_available = 200_000
    api._quotes["LIGTOP"] = {"price": 300_000, "change_pct": 3.0}
    api._quotes["RANK2"] = {"price": 250_000, "change_pct": 2.0}
    api._quotes["DEFPEER"] = {"price": 40_000, "change_pct": 1.8}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_entry_order_type="best",
        swing_chart_review_enabled=False,
        swing_cash_ratio=1.0,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"

    model = pd.DataFrame(
        [
            {"code": "LIGTOP", "name": "LIG디펜스", "industry_bucket_name": "방산"},
            {"code": "RANK2", "name": "2위후보", "industry_bucket_name": "반도체"},
            {"code": "DEFPEER", "name": "한화방산", "industry_bucket_name": "방산", "avg_value_20d": 500_000_000_000},
        ]
    )
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=model,
        etf=pd.DataFrame(),
        merged=model.copy(),
        quote_codes=["LIGTOP", "RANK2", "DEFPEER"],
    )

    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=["LIGTOP", "RANK2"]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={
                "LIGTOP": api.quote("LIGTOP"),
                "RANK2": api.quote("RANK2"),
                "DEFPEER": api.quote("DEFPEER"),
            },
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "DEFPEER", "qty": 5, "order_type": "limit", "price": 40_050}
    ]
    assert "DEFPEER" in bot.state.open_positions
    assert "LIGTOP" not in bot.state.open_positions
    assert "RANK2" not in bot.state.open_positions
    assert bot.state.pass_reasons_today == {}


def test_ranked_swing_entry_skips_held_first_pick_and_buys_second_with_600k_budget(tmp_path) -> None:
    api = FakeAPI()
    api._cash_available = 1_200_000
    api._quotes["FIRST"] = {"price": 100_000, "change_pct": 1.0}
    api._quotes["SECOND"] = {"price": 100_000, "change_pct": 0.8}
    api._positions = [
        {"code": "FIRST", "qty": 8, "avg_price": 100_000.0, "current_price": 100_000},
    ]
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        max_swing_positions=2,
        swing_rank_budget_enabled=True,
        swing_rank_budget_weights=(0.50, 0.375),
        swing_multi_position_activation_at="2026-08-12T14:00:00+09:00",
        swing_chart_review_enabled=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260813"
    bot.state.open_positions["FIRST"] = PositionState(
        type="S",
        entry_time="2026-08-13T09:05:00+09:00",
        entry_price=100_000.0,
        qty=8,
        highest_price=100_000.0,
        entry_date="20260813",
    )
    candidates = SimpleNamespace(
        model=pd.DataFrame(
            [
                {"code": "FIRST", "name": "1순위"},
                {"code": "SECOND", "name": "2순위"},
            ]
        ),
        etf=pd.DataFrame(),
    )

    with patch(
        "backend.services.trading_engine.bot.rank_swing_codes",
        return_value=["FIRST", "SECOND"],
    ):
        bot._try_enter_swing(
            now=datetime(2026, 8, 13, 13, 5),
            regime="RISK_ON",
            candidates=candidates,
            quotes={
                "FIRST": api.quote("FIRST"),
                "SECOND": api.quote("SECOND"),
            },
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "SECOND", "qty": 6, "order_type": "limit", "price": 100_100},
    ]
    assert bot.state.open_positions["SECOND"].qty == 6


def test_ranked_swing_activation_blocks_legacy_position_until_it_is_gone() -> None:
    cfg = TradeEngineConfig(
        max_swing_positions=2,
        swing_rank_budget_enabled=True,
        swing_multi_position_activation_at="2026-08-12T14:00:00+09:00",
    )
    state = new_state("20260812")
    state.open_positions["028260"] = PositionState(
        type="S",
        entry_time="2026-08-12T09:20:00+09:00",
        entry_price=358_000.0,
        qty=4,
        highest_price=361_000.0,
        entry_date="20260812",
    )

    ok, reason = can_enter(
        "S",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 8, 12, 14, 5),
        config=cfg,
    )

    assert ok is False
    assert reason == "MAX_SWING_POSITIONS"

    state.open_positions.clear()
    state.open_positions["FIRST"] = PositionState(
        type="S",
        entry_time="2026-08-13T09:05:00+09:00",
        entry_price=100_000.0,
        qty=8,
        highest_price=100_000.0,
        entry_date="20260813",
    )
    state.trade_date = "20260813"

    ok, reason = can_enter(
        "S",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 8, 13, 14, 5),
        config=cfg,
    )

    assert ok is True
    assert reason == "OK"


def test_ranked_swing_mode_limits_concurrent_day_position_to_one() -> None:
    cfg = TradeEngineConfig(
        max_day_positions=2,
        swing_rank_budget_enabled=True,
    )
    state = new_state("20260813")
    state.open_positions["DAY01"] = PositionState(
        type="T",
        entry_time="2026-08-13T13:00:00+09:00",
        entry_price=100_000.0,
        qty=2,
        highest_price=100_000.0,
        entry_date="20260813",
    )

    ok, reason = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 8, 13, 14, 5),
        config=cfg,
        available_cash_krw=1_000_000,
    )

    assert ok is False
    assert reason == "MAX_DAY_POSITIONS"


def test_swing_scale_in_fails_closed_without_chart_then_buys_when_trend_is_alive(tmp_path) -> None:
    api = FakeAPI()
    api._cash_available = 624_000
    api._quotes["FIRST"] = {"price": 97_000, "change_pct": -3.0}
    api._quotes["SECOND"] = {"price": 100_000, "change_pct": 0.0}
    api._positions = [
        {"code": "FIRST", "qty": 8, "avg_price": 100_000.0, "current_price": 97_000},
        {"code": "SECOND", "qty": 6, "avg_price": 100_000.0, "current_price": 100_000},
    ]
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        max_swing_positions=2,
        swing_rank_budget_enabled=True,
        swing_scale_in_enabled=True,
        swing_scale_in_trigger_pct=-0.03,
        swing_multi_position_activation_at="2026-02-15T00:00:00+09:00",
        swing_trend_ma_window=3,
        swing_trend_lookback_bars=5,
        swing_chart_review_enabled=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    for code, qty in (("FIRST", 8), ("SECOND", 6)):
        bot.state.open_positions[code] = PositionState(
            type="S",
            entry_time="2026-02-15T09:05:00+09:00",
            entry_price=100_000.0,
            qty=qty,
            highest_price=100_000.0,
            entry_date="20260215",
        )
    candidates = SimpleNamespace(model=pd.DataFrame(), etf=pd.DataFrame())

    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=[]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 5),
            regime="RISK_ON",
            candidates=candidates,
            quotes={},
        )

    assert api.order_calls == []

    api._bars[("FIRST", "20260216")] = pd.DataFrame(
        {"close": [95_000, 95_000, 96_000, 96_000, 96_000]}
    )
    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=[]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 5),
            regime="RISK_ON",
            candidates=candidates,
            quotes={},
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "FIRST", "qty": 3, "order_type": "limit", "price": 97_100},
    ]
    assert bot.state.open_positions["FIRST"].qty == 11
    assert "FIRST" in bot.state.blacklist_today
