from .trading_engine_support import *  # noqa: F401,F403

def test_passes_day_intraday_confirmation_allows_momentum_pullback_with_quote_fallback() -> None:
    from backend.services.trading_engine.intraday import passes_day_intraday_confirmation

    asof = "20260422"
    api = FakeAPI()
    api._quotes["CHASE1"] = {
        "price": 14540,
        "open": 12150,
        "high": 15420,
        "low": 12150,
        "change_pct": 19.97,
    }
    api.intraday_bars = lambda code, asof, lookback=120: _make_intraday_bars(  # type: ignore[attr-defined]
        asof,
        [14660, 14570, 14540],
    )

    cfg = TradeEngineConfig(
        day_intraday_min_window_change_pct=0.2,
        day_intraday_min_last_bar_change_pct=-0.2,
        day_intraday_max_retrace_from_high_pct=-0.8,
        day_momentum_pullback_min_day_change_pct=12.0,
        day_momentum_pullback_min_window_change_pct=-1.0,
        day_momentum_pullback_min_last_bar_change_pct=-0.25,
        day_momentum_pullback_max_retrace_from_high_pct=-1.8,
    )

    ok, meta = passes_day_intraday_confirmation(
        api,
        trade_date=asof,
        code="CHASE1",
        config=cfg,
    )

    assert ok is True
    assert meta["reason"] == "MOMENTUM_PULLBACK_OK"
    assert meta["day_change_pct"] == 19.97

def test_bot_risk_on_exits_existing_risk_off_parking(tmp_path) -> None:
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

    asof = "20260324"
    api = FakeAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 101, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_100, "change_pct": 0.5}
    api._positions = [{"code": "440650", "qty": 50, "avg_price": 10_000.0}]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-23T10:05:00",
        entry_price=10_000.0,
        qty=50,
        highest_price=10_000.0,
        entry_date="20260323",
    )
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 24, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_ON"
    assert api.order_calls[0] == {
        "side": "SELL",
        "code": "440650",
        "qty": 50,
        "order_type": "MKT",
        "price": None,
    }
    assert "440650" not in bot.state.open_positions
    assert any(text.startswith("[청산][파킹][위험선호 전환] 440650") for text in notifier.texts)

def test_bot_risk_on_failed_parking_exit_keeps_position(tmp_path) -> None:
    class RejectingAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": False, "msg": "매도주문이 거부되었습니다"}

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

    asof = "20260324"
    api = RejectingAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 101, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_100, "change_pct": 0.5}
    api._positions = [{"code": "440650", "qty": 50, "avg_price": 10_000.0}]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-23T10:05:00",
        entry_price=10_000.0,
        qty=50,
        highest_price=10_000.0,
        entry_date="20260323",
    )
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 24, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_ON"
    assert api.order_calls == [
        {"side": "SELL", "code": "440650", "qty": 50, "order_type": "MKT", "price": None}
    ]
    assert "440650" in bot.state.open_positions
    assert not any(text.startswith("[청산][파킹][위험선호 전환] 440650") for text in notifier.texts)

def test_swing_can_retry_in_second_window_after_morning_no_pick(tmp_path) -> None:
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
    api._quotes["005930"] = {"price": 100_000, "change_pct": 1.2}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"

    candidates = SimpleNamespace(
        model=pd.DataFrame([{"code": "005930", "name": "삼성전자"}]),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=[]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={},
        )

    assert api.order_calls == []
    assert bot.state.swing_entries_today == 0
    assert bot.state.pass_reasons_today.get("NO_SWING_PICK") == 1
    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[스윙][보류]")]
    assert len(swing_skip_msgs) == 1
    assert "후보" in swing_skip_msgs[0]
    assert "매수는 쉬어갔어" in swing_skip_msgs[0]
    assert "09:55-10:10" in swing_skip_msgs[0]

    with patch("backend.services.trading_engine.bot.rank_swing_codes", return_value=["005930"]):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
        )

    assert bot.state.swing_entries_today == 1
    assert "005930" in bot.state.open_positions
    assert api.order_calls == [
            {
                "side": "BUY",
                "code": "005930",
                "qty": 8,
                "order_type": "best",
                "price": None,
            }
        ]

def test_swing_no_candidate_notified_once_per_window(tmp_path) -> None:
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
        swing_chart_review_enabled=False,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"

    empty_candidates = SimpleNamespace(
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
    )

    bot._try_enter_swing(
        now=datetime(2026, 2, 16, 9, 10),
        regime="RISK_ON",
        candidates=empty_candidates,
        quotes={},
    )
    bot._try_enter_swing(
        now=datetime(2026, 2, 16, 9, 14),
        regime="RISK_ON",
        candidates=empty_candidates,
        quotes={},
    )

    assert api.order_calls == []
    assert bot.state.pass_reasons_today.get("NO_CANDIDATE") == 2
    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[스윙][보류]")]
    assert len(swing_skip_msgs) == 1
    assert "스윙 후보" in swing_skip_msgs[0]
    assert "09:55-10:10" in swing_skip_msgs[0]

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
    assert abs(float(bot.state.open_positions["005930"].locked_profit_pct or 0.0) - 0.05) < 1e-9

def test_locked_profit_position_exits_immediately_after_profit_floor_break(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.2}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_take_profit_mode="trailing",
        swing_trail_start=0.50,
        swing_chart_review_enabled=False,
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

    api._quotes["005930"] = {"price": 104_000, "change_pct": 0.8}
    bot.monitor_positions(now=datetime(2026, 2, 16, 13, 14))

    assert any(call["side"] == "SELL" and call["code"] == "005930" for call in api.order_calls)
    assert "005930" not in bot.state.open_positions

def test_day_position_arms_profit_lock_and_exits_on_retrace() -> None:
    cfg = TradeEngineConfig(
        day_lock_profit_trigger_pct=0.009,
        day_lock_profit_floor_pct=0.002,
        day_lock_retrace_gap_pct=0.006,
    )
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=101_500.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=101_500.0,
        now=datetime(2026, 2, 16, 9, 20),
        config=cfg,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.015
    assert abs(float(position.locked_profit_pct or 0.0) - 0.009) < 1e-9

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=100_800.0,
        now=datetime(2026, 2, 16, 9, 24),
        config=cfg,
    )

    assert exit_now is True
    assert reason == "LOCK"
    assert round(pnl_pct, 4) == 0.008

def test_day_position_volatility_aware_lock_allows_early_pullback() -> None:
    cfg = TradeEngineConfig(
        day_lock_profit_trigger_pct=0.009,
        day_lock_profit_floor_pct=0.005,
        day_lock_retrace_gap_pct=0.006,
        day_take_profit_pct=0.050,
    )
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=101_800.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=101_800.0,
        now=datetime(2026, 2, 16, 9, 12),
        config=cfg,
        day_lock_retrace_gap_pct_override=0.013,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.018
    assert abs(float(position.locked_profit_pct or 0.0) - 0.005) < 1e-9

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=100_900.0,
        now=datetime(2026, 2, 16, 9, 16),
        config=cfg,
        day_lock_retrace_gap_pct_override=0.013,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.009

def test_day_hold_match_does_not_tighten_lock_to_full_profit(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005880"] = {"price": 101_800, "change_pct": 1.8}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    bot.state.open_positions["005880"] = PositionState(
        type="T",
        entry_time="2026-02-16T09:08:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=100_000.0,
        entry_date="20260216",
        locked_profit_pct=0.005,
    )

    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame([{"code": "005880"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["005880"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 12),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005880": api.quote("005880")},
            news_signal=None,
        )

    assert api.order_calls == []
    assert "005880" in bot.state.open_positions
    assert abs(float(bot.state.open_positions["005880"].locked_profit_pct or 0.0) - 0.005) < 1e-9
    assert abs(float(bot.state.open_positions["005880"].highest_price or 0.0) - 101_800.0) < 1e-9

def test_day_entry_windows_progress_across_four_intraday_slots() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")

    ok_first_window, reason_first_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )
    ok_third_window_before_fill, reason_third_window_before_fill = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    state.day_entries_today = 1
    state.day_entry_windows_used_today = {0}
    ok_second_morning, reason_second_morning = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )
    ok_second_window, reason_second_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 10, 0),
        config=cfg,
    )

    state.day_entries_today = 2
    state.day_entry_windows_used_today = {0, 1}
    ok_third_window, reason_third_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )
    ok_fourth_window_before_third_fill, reason_fourth_window_before_third_fill = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 14, 0),
        config=cfg,
    )

    state.day_entries_today = 3
    state.day_entry_windows_used_today = {0, 1, 2}
    ok_fourth_window, reason_fourth_window = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 14, 0),
        config=cfg,
    )

    assert ok_first_window is True
    assert reason_first_window == "OK"
    assert ok_third_window_before_fill is True
    assert reason_third_window_before_fill == "OK"
    assert ok_second_morning is False
    assert reason_second_morning == "ENTRY_WINDOW_CLOSED"
    assert ok_second_window is True
    assert reason_second_window == "OK"
    assert ok_third_window is True
    assert reason_third_window == "OK"
    assert ok_fourth_window_before_third_fill is True
    assert reason_fourth_window_before_third_fill == "OK"
    assert ok_fourth_window is True
    assert reason_fourth_window == "OK"

def test_day_afternoon_entry_blocks_after_two_stoploss_sized_losses() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")
    state.day_entries_today = 2
    state.realized_pnl_today = -4_800.0

    ok_afternoon_blocked, reason_afternoon_blocked = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    state.realized_pnl_today = -4_700.0
    ok_afternoon_allowed, reason_afternoon_allowed = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    assert ok_afternoon_blocked is False
    assert reason_afternoon_blocked == "DAY_AFTERNOON_LOSS_LIMIT"
    assert ok_afternoon_allowed is True
    assert reason_afternoon_allowed == "OK"

def test_rank_daytrade_codes_prefers_near_high_strength_over_faded_liquidity() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(
            [
                {
                    "code": "FADE01",
                    "name": "Fade Corp",
                    "avg_value_5d": 500_000_000_000,
                    "close": 101.0,
                    "change_pct": 1.0,
                    "is_etf": False,
                },
                {
                    "code": "LEAD01",
                    "name": "Leader Corp",
                    "avg_value_5d": 60_000_000_000,
                    "close": 106.0,
                    "change_pct": 3.0,
                    "is_etf": False,
                },
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["FADE01", "LEAD01"],
    )
    quotes = {
        "FADE01": {
            "price": 101.0,
            "open": 101.0,
            "high": 106.0,
            "low": 100.0,
            "change_pct": 1.0,
        },
        "LEAD01": {
            "price": 106.0,
            "open": 103.0,
            "high": 107.0,
            "low": 102.0,
            "change_pct": 3.0,
        },
    }

    ranked = rank_daytrade_codes(candidates, quotes, cfg)

    assert ranked[:2] == ["LEAD01", "FADE01"]

def test_pick_swing_prefers_sector_etf_on_theme_day() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=True)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": 1_800_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 110.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "000660",
                    "name": "SK하이닉스",
                    "avg_value_20d": 1_200_000_000_000,
                    "ma20": 95.0,
                    "ma60": 90.0,
                    "close": 103.0,
                    "change_pct": 3.2,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(
            [
                {
                    "code": "ETF001",
                    "name": "KODEX 반도체",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 98.0,
                    "ma60": 93.0,
                    "close": 108.0,
                    "change_pct": 2.8,
                    "is_etf": True,
                },
                {
                    "code": "ETF002",
                    "name": "TIGER 반도체TOP10",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 99.0,
                    "ma60": 94.0,
                    "close": 109.0,
                    "change_pct": 3.1,
                    "is_etf": True,
                }
            ]
        ),
        merged=pd.DataFrame(),
        quote_codes=["005930", "000660", "ETF001", "ETF002"],
    )
    quotes = {
        "005930": {"price": 110.0, "change_pct": 4.0},
        "000660": {"price": 103.0, "change_pct": 3.2},
        "ETF001": {"price": 108.0, "change_pct": 2.8},
        "ETF002": {"price": 109.0, "change_pct": 3.1},
    }
    news_signal = NewsSentimentSignal(
        market_score=0.3,
        sector_scores={"semiconductor": 0.75},
        sector_keywords={"semiconductor": ("반도체", "삼성전자", "sk하이닉스")},
        article_count=50,
    )

    picked = pick_swing(candidates, quotes, cfg, news_signal=news_signal)

    assert picked == "ETF001"

def test_pick_swing_keeps_stock_when_theme_breadth_is_not_met() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=True)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": 1_800_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 110.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(
            [
                {
                    "code": "ETF001",
                    "name": "KODEX 반도체",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 98.0,
                    "ma60": 93.0,
                    "close": 108.0,
                    "change_pct": 2.8,
                    "is_etf": True,
                }
            ]
        ),
        merged=pd.DataFrame(),
        quote_codes=["005930", "ETF001"],
    )
    quotes = {
        "005930": {"price": 110.0, "change_pct": 4.0},
        "ETF001": {"price": 108.0, "change_pct": 2.8},
    }
    news_signal = NewsSentimentSignal(
        market_score=0.3,
        sector_scores={"semiconductor": 0.75},
        sector_keywords={"semiconductor": ("반도체", "삼성전자", "sk하이닉스")},
        article_count=50,
    )

    picked = pick_swing(candidates, quotes, cfg, news_signal=news_signal)

    assert picked == "005930"

def test_pick_swing_prefers_stock_holding_near_high_over_faded_large_cap() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "FADE01",
                    "name": "Fade LargeCap",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 108.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "LEAD01",
                    "name": "Leader LargeCap",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100.0,
                    "ma60": 96.0,
                    "close": 109.0,
                    "change_pct": 3.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["FADE01", "LEAD01"],
    )
    quotes = {
        "FADE01": {
            "price": 108.0,
            "open": 112.0,
            "high": 116.0,
            "low": 107.0,
            "change_pct": 4.0,
        },
        "LEAD01": {
            "price": 109.0,
            "open": 106.0,
            "high": 110.0,
            "low": 105.0,
            "change_pct": 3.5,
        },
    }

    picked = pick_swing(candidates, quotes, cfg, news_signal=None)

    assert picked == "LEAD01"
