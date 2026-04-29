from .trading_engine_support import *  # noqa: F401,F403

def test_bot_rebuys_risk_off_parking_after_stale_local_position_is_dropped(tmp_path) -> None:
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

    asof = "20260325"
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
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-23T10:44:00",
        entry_price=12_475.0,
        qty=72,
        highest_price=12_475.0,
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

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 95, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["440650"].qty == 95
    assert any(text.startswith("[상태동기화][정리] 440650") for text in notifier.texts)
    assert any(text.startswith("[진입][파킹] 440650") for text in notifier.texts)

def test_bot_risk_off_failed_parking_order_does_not_emit_fake_entry(tmp_path) -> None:
    class RejectingAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": False, "msg": "주문가능금액을 초과 했습니다"}

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

    asof = "20260325"
    api = RejectingAPI()
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
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 95, "order_type": "best", "price": None},
        {"side": "BUY", "code": "440650", "qty": 94, "order_type": "best", "price": None},
    ]
    assert "440650" not in bot.state.open_positions
    assert not any(text.startswith("[진입][파킹] 440650") for text in notifier.texts)

def test_bot_risk_off_reduces_qty_after_insufficient_cash_rejection(tmp_path) -> None:
    class TightCashAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            if side == "BUY" and code == "440650" and qty >= 73:
                return {"success": False, "msg": "주문가능금액을 초과 했습니다"}
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": price or self.quote(code).get("price", 0),
            }

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

    asof = "20260325"
    api = TightCashAPI()
    api._cash_available = 954_514
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 12_365, "change_pct": 0.1}

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
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 73, "order_type": "best", "price": None},
        {"side": "BUY", "code": "440650", "qty": 72, "order_type": "best", "price": None},
    ]
    assert bot.state.open_positions["440650"].qty == 72
    assert any(text.startswith("[진입][파킹] 440650 수량=72") for text in notifier.texts)

def test_bot_risk_off_uses_broker_buyable_amount_before_parking_order(tmp_path) -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "440650"
            assert order_type == "best"
            assert price is None or price > 0
            return {
                "ord_psbl_cash": 900_000,
                "nrcvb_buy_amt": 900_000,
                "nrcvb_buy_qty": 68,
                "max_buy_qty": 72,
                "psbl_qty_calc_unpr": 12_500,
            }

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

    asof = "20260325"
    api = BuyableAPI()
    api._cash_available = 2_000_000
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 12_365, "change_pct": 0.1}

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
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 69, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["440650"].qty == 69
    assert any(text.startswith("[진입][파킹] 440650 수량=69") for text in notifier.texts)

def test_bot_risk_off_does_not_top_up_existing_parking_position(tmp_path) -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "440650"
            assert order_type == "best"
            assert price is None or price > 0
            return {
                "ord_psbl_cash": 100_000,
                "nrcvb_buy_amt": 100_000,
                "nrcvb_buy_qty": 9,
                "max_buy_qty": 9,
                "psbl_qty_calc_unpr": 10_000,
            }

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

    asof = "20260326"
    api = BuyableAPI()
    api._cash_available = 500_000
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_000, "change_pct": 0.1}
    api._positions = [{"code": "440650", "qty": 50, "avg_price": 10_000.0}]

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
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-26T09:00:00",
        entry_price=10_000.0,
        qty=50,
        highest_price=10_000.0,
        entry_date=asof,
    )
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
            out = bot.run_once(now=datetime(2026, 3, 26, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == []
    assert bot.state.open_positions["440650"].qty == 50
    assert not any(text.startswith("[진입][파킹] 440650") for text in notifier.texts)
