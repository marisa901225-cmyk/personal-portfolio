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

