from .trading_engine_support import *  # noqa: F401,F403

def test_bot_passes_on_holiday_without_order(tmp_path) -> None:
    api = FakeAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [{"date": "20260213", "close": 100, "volume": 1}]
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_chart_review_enabled=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    result = bot.run_once(now=datetime(2026, 2, 14, 8, 50))

    assert result["status"] == "PASS"
    assert result["reason"] == "HOLIDAY"
    assert api.order_calls == []

def test_bot_holiday_is_checked_once_per_day(tmp_path) -> None:
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

    class CountAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.daily_bars_calls = 0

        def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
            self.daily_bars_calls += 1
            return super().daily_bars(code, end, lookback)

    api = CountAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [{"date": "20260213", "close": 100, "volume": 1}]
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]

    out1 = bot.run_once(now=datetime(2026, 2, 14, 8, 50))
    out2 = bot.run_once(now=datetime(2026, 2, 14, 9, 0))

    assert out1["status"] == "PASS"
    assert out1["reason"] == "HOLIDAY"
    assert out2["status"] == "PASS"
    assert out2["reason"] == "HOLIDAY"
    assert api.daily_bars_calls == 2
    assert bot.state.pass_reasons_today.get("HOLIDAY") == 2

    holiday_pass_msgs = [t for t in notifier.texts if t.startswith("[보류] 휴장일")]
    assert len(holiday_pass_msgs) == 1

def test_bot_daily_max_loss_pass_notified_once_per_day(tmp_path) -> None:
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

    bot._pass("DAILY_MAX_LOSS", regime="RISK_ON")
    bot._pass("DAILY_MAX_LOSS", regime="RISK_ON")

    assert bot.state.pass_reasons_today.get("DAILY_MAX_LOSS") == 2
    daily_max_loss_msgs = [t for t in notifier.texts if t.startswith("[보류] 일일 손실 한도 도달")]
    assert len(daily_max_loss_msgs) == 1

def test_bot_risk_off_pass_notified_once_per_day(tmp_path) -> None:
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

    bot._pass("RISK_OFF", regime="RISK_OFF")
    bot._pass("RISK_OFF", regime="RISK_OFF")

    assert bot.state.pass_reasons_today.get("RISK_OFF") == 2
    risk_off_msgs = [t for t in notifier.texts if t.startswith("[보류] 위험회피 장세")]
    assert len(risk_off_msgs) == 1

def test_bot_candidate_notification_visible_in_risk_off(tmp_path) -> None:
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

    candidates = SimpleNamespace(
        popular=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_5d": 210_000_000_000,
                    "avg_value_20d": 205_000_000_000,
                }
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_5d": 210_000_000_000,
                    "avg_value_20d": 205_000_000_000,
                }
            ]
        )
    )

    now = datetime(2026, 2, 16, 9, 10)  # default entry window 안
    bot._maybe_notify_candidates(now, candidates, regime="RISK_OFF")
    bot._maybe_notify_candidates(now, candidates, regime="RISK_OFF")  # same window dedupe

    candidate_msgs = [t for t in notifier.texts if t.startswith("⚡ [진입창] [단타] 후보 종목 (위험회피)")]
    assert len(candidate_msgs) == 1
    assert "관찰 전용" in candidate_msgs[0]
    assert "440650" in candidate_msgs[0]
    assert "005930" in candidate_msgs[0]

def test_bot_candidate_notification_prefers_ranked_display_candidates(tmp_path) -> None:
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

    candidates = SimpleNamespace(
        popular=pd.DataFrame(
            [
                {"code": "RAW001", "name": "원시후보", "avg_value_5d": 210_000_000_000},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "RAW001", "name": "원시후보", "avg_value_5d": 210_000_000_000},
            ]
        )
    )
    display_candidates = pd.DataFrame(
        [
            {"code": "TOP001", "name": "정제후보", "avg_value_5d": 180_000_000_000},
        ]
    )

    now = datetime(2026, 2, 16, 9, 10)
    bot._maybe_notify_candidates(
        now,
        candidates,
        regime="RISK_ON",
        display_candidates=display_candidates,
    )

    candidate_msgs = [t for t in notifier.texts if t.startswith("⚡ [진입창] [단타] 후보 종목 (위험선호)")]
    assert len(candidate_msgs) == 1
    assert "TOP001" in candidate_msgs[0]
    assert "RAW001" not in candidate_msgs[0]

def test_bot_candidate_notification_sends_day_and_swing_separately(tmp_path) -> None:
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

    candidates = SimpleNamespace(
        popular=pd.DataFrame(
            [
                {"code": "DAY001", "name": "단타후보", "avg_value_5d": 170_000_000_000},
            ]
        ),
        model=pd.DataFrame(
            [
                {"code": "SWG001", "name": "스윙후보", "avg_value_20d": 320_000_000_000},
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "DAY001", "name": "단타후보", "avg_value_5d": 170_000_000_000},
                {"code": "SWG001", "name": "스윙후보", "avg_value_20d": 320_000_000_000},
            ]
        ),
    )
    display_candidates = pd.DataFrame(
        [
            {"code": "DAY001", "name": "단타후보", "avg_value_5d": 170_000_000_000},
        ]
    )

    bot._maybe_notify_candidates(
        datetime(2026, 2, 16, 9, 10),
        candidates,
        regime="RISK_ON",
        display_candidates=display_candidates,
    )

    assert len(notifier.texts) == 2
    assert notifier.texts[0].startswith("📈 [진입창] [스윙] 후보 종목 (위험선호)")
    assert "SWG001" in notifier.texts[0]
    assert notifier.texts[1].startswith("⚡ [진입창] [단타] 후보 종목 (위험선호)")
    assert "DAY001" in notifier.texts[1]

def test_bot_risk_off_parks_cash_in_bond_etf(tmp_path) -> None:
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

    asof = "20260323"
    api = FakeAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_000, "change_pct": 0.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
        risk_off_parking_cash_ratio=0.95,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 23, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 95, "order_type": "best", "price": None}
    ]
    assert bot.state.pass_reasons_today.get("RISK_OFF") == 1
    assert "440650" in bot.state.open_positions
    assert bot.state.open_positions["440650"].type == "P"
    assert any(text.startswith("[진입][파킹] 440650") for text in notifier.texts)

