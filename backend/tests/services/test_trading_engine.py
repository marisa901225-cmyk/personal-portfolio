from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from backend.services.trading_engine.bot import HybridTradingBot
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.execution import exit_position
from backend.services.trading_engine.market_calendar import get_last_trading_day, is_trading_day
from backend.services.trading_engine.regime import detect_intraday_circuit_breaker, get_regime
from backend.services.trading_engine.risk import can_enter
from backend.services.trading_engine.strategy import Candidates
from backend.services.trading_engine.screeners import model_screener, popular_screener
from backend.services.trading_engine.state import PositionState, new_state


class FakeAPI:
    def __init__(self) -> None:
        self._volume_rank: dict[tuple[str, str], list[dict]] = {}
        self._market_cap_rank: dict[str, list[dict]] = {}
        self._bars: dict[tuple[str, str], pd.DataFrame] = {}
        self._quotes: dict[str, dict] = {}
        self._positions: list[dict] = []
        self._cash_available: int = 1_000_000
        self.order_calls: list[dict] = []

    def volume_rank(self, kind: str, top_n: int, asof: str) -> list[dict]:
        del top_n
        return list(self._volume_rank.get((kind, asof), []))

    def market_cap_rank(self, top_k: int, asof: str) -> list[dict]:
        del top_k
        return list(self._market_cap_rank.get(asof, []))

    def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
        del lookback
        return self._bars.get((code, end), pd.DataFrame())

    def quote(self, code: str) -> dict:
        return dict(self._quotes.get(code, {"price": 0, "change_pct": 0.0}))

    def positions(self) -> list[dict]:
        return list(self._positions)

    def cash_available(self) -> int:
        return self._cash_available

    def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
        self.order_calls.append(
            {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
        )
        return {"order_id": f"{side}-{code}", "filled_qty": qty, "avg_price": price or self.quote(code).get("price", 0)}

    def open_orders(self) -> list[dict]:
        return []

    def cancel_order(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": "cancelled"}


def _make_bars(asof: str, n: int, start_close: float, step: float, value: float | None = None) -> pd.DataFrame:
    end = datetime.strptime(asof, "%Y%m%d")
    rows = []
    close = start_close
    for i in range(n):
        day = end - timedelta(days=n - i - 1)
        row = {
            "date": day.strftime("%Y%m%d"),
            "close": close,
            "volume": 1_000_000,
        }
        if value is not None:
            row["value"] = value
        rows.append(row)
        close += step
    return pd.DataFrame(rows)


def _make_bars_from_closes(asof: str, closes: list[float], value: float | None = None) -> pd.DataFrame:
    end = datetime.strptime(asof, "%Y%m%d")
    start = end - timedelta(days=len(closes) - 1)
    rows = []
    for offset, close in enumerate(closes):
        day = start + timedelta(days=offset)
        row = {
            "date": day.strftime("%Y%m%d"),
            "close": close,
            "volume": 1_000_000,
        }
        if value is not None:
            row["value"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _make_intraday_bars(
    asof: str,
    closes: list[float],
    *,
    start_time: str = "090000",
    last_change_pct: float | None = None,
) -> pd.DataFrame:
    base = datetime.strptime(asof + start_time, "%Y%m%d%H%M%S")
    rows: list[dict] = []
    for idx, close in enumerate(closes):
        ts = base + timedelta(minutes=idx)
        row = {
            "date": ts.strftime("%Y%m%d"),
            "time": ts.strftime("%H%M%S"),
            "timestamp": ts.strftime("%Y%m%d%H%M%S"),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        if last_change_pct is not None and idx == len(closes) - 1:
            row["change_pct"] = last_change_pct
        rows.append(row)
    return pd.DataFrame(rows)


def test_popular_screener_intersection_and_proxy() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
        {"code": "000002", "name": "Beta", "rank": 2},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
        {"code": "000003", "name": "Gamma", "rank": 2},
    ]
    api._bars[("000001", asof)] = _make_bars(asof, 10, 100, 1, value=None)  # proxy path
    api._bars[("000002", asof)] = _make_bars(asof, 10, 90, 0, value=20_000_000_000)
    api._bars[("000003", asof)] = _make_bars(asof, 10, 80, 0, value=10_000_000_000)

    out = popular_screener(api, asof=asof, include_etf=False)

    assert not out.empty
    assert "000001" in set(out["code"])
    row = out[out["code"] == "000001"].iloc[0]
    assert bool(row["used_value_proxy"]) is True


def test_model_screener_filters_etf_and_applies_ma_chain() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._market_cap_rank[asof] = [
        {"code": "111111", "name": "GoodStock", "mcap": 2_000_000_000_000},
        {"code": "222222", "name": "KODEX ETF", "mcap": 3_000_000_000_000, "is_etf": True},
    ]
    api._bars[("111111", asof)] = _make_bars(asof, 140, 100, 1, value=700_000_000_000)
    api._bars[("222222", asof)] = _make_bars(asof, 140, 100, 1, value=900_000_000_000)

    out = model_screener(api, asof=asof)

    assert not out.empty
    assert set(out["code"]) == {"111111"}


def test_model_screener_allows_relaxed_large_cap_when_broker_omits_mcap() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._market_cap_rank[asof] = [
        {"code": "333333", "name": "LargeCapNoMetric", "mcap": 0},
    ]
    api._bars[("333333", asof)] = _make_bars(asof, 100, 100, 1, value=900_000_000_000)

    out = model_screener(api, asof=asof)

    assert not out.empty
    row = out[out["code"] == "333333"].iloc[0]
    assert row["trend_tier"] == "relaxed"


def test_market_calendar_fallback_uses_proxy_etf_bars() -> None:
    api = FakeAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [
            {"date": "20260212", "close": 100, "volume": 1},
            {"date": "20260213", "close": 101, "volume": 1},
        ]
    )
    api._bars[("069500", "20260213")] = pd.DataFrame(
        [
            {"date": "20260213", "close": 101, "volume": 1},
        ]
    )

    assert is_trading_day(api, "20260214") is False
    assert get_last_trading_day(api, "20260214") == "20260213"


def test_bot_passes_on_holiday_without_order(tmp_path) -> None:
    api = FakeAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [{"date": "20260213", "close": 100, "volume": 1}]
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
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

    holiday_pass_msgs = [t for t in notifier.texts if t.startswith("[PASS] HOLIDAY")]
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
    daily_max_loss_msgs = [t for t in notifier.texts if t.startswith("[PASS] DAILY_MAX_LOSS")]
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
    risk_off_msgs = [t for t in notifier.texts if t.startswith("[PASS] RISK_OFF")]
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

    candidate_msgs = [t for t in notifier.texts if t.startswith("🎯 [Entry Window] Scanned Symbols (RISK_OFF)")]
    assert len(candidate_msgs) == 1
    assert "관찰 전용" in candidate_msgs[0]
    assert "440650" in candidate_msgs[0]
    assert "005930" in candidate_msgs[0]


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
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650") for text in notifier.texts)


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
    assert any(text.startswith("[STATE_SYNC][DROP] 440650") for text in notifier.texts)
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650") for text in notifier.texts)


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
    assert not any(text.startswith("[ENTRY][P][RISK_OFF] 440650") for text in notifier.texts)


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
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650 qty=72") for text in notifier.texts)


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
        {"side": "BUY", "code": "440650", "qty": 68, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["440650"].qty == 68
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650 qty=68") for text in notifier.texts)


def test_bot_risk_off_tops_up_existing_parking_position(tmp_path) -> None:
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
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 9, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["440650"].qty == 59
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650 qty=9") for text in notifier.texts)


def test_exit_position_caps_sell_qty_by_broker_sellable_amount() -> None:
    class SellableAPI(FakeAPI):
        def sell_order_capacity(self, code: str) -> dict:
            assert code == "440650"
            return {
                "ord_psbl_qty": 30,
                "hldg_qty": 50,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": price or self.quote(code).get("price", 0),
            }

    api = SellableAPI()
    api._quotes["440650"] = {"price": 12_500, "change_pct": 0.1}
    state = new_state("20260325")
    state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-25T10:00:00",
        entry_price=12_000.0,
        qty=50,
        highest_price=12_500.0,
        entry_date="20260325",
        bars_held=0,
    )

    result = exit_position(
        api,
        state,
        code="440650",
        reason="RISK_ON",
        now=datetime(2026, 3, 25, 10, 30),
    )

    assert result is not None
    assert result.qty == 30
    assert api.order_calls == [
        {"side": "SELL", "code": "440650", "qty": 30, "order_type": "MKT", "price": None}
    ]
    assert "440650" in state.open_positions
    assert state.open_positions["440650"].qty == 20
    assert state.realized_pnl_today == 15_000.0


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
    assert any(text.startswith("[EXIT][P][RISK_ON] 440650") for text in notifier.texts)


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
    assert not any(text.startswith("[EXIT][P][RISK_ON] 440650") for text in notifier.texts)


def test_swing_can_retry_in_second_window_after_morning_no_pick(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005930"] = {"price": 100_000, "change_pct": 1.2}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"

    candidates = SimpleNamespace(
        model=pd.DataFrame([{"code": "005930", "name": "삼성전자"}]),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.pick_swing", return_value=None):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={},
        )

    assert api.order_calls == []
    assert bot.state.swing_entries_today == 0
    assert bot.state.pass_reasons_today.get("NO_SWING_PICK") == 1

    with patch("backend.services.trading_engine.bot.pick_swing", return_value="005930"):
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
            "qty": 7,
            "order_type": "best",
            "price": None,
        }
    ]


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


def test_day_entry_window_defaults_to_morning_only() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")

    ok_morning, reason_morning = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )
    ok_lunch, reason_lunch = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    assert ok_morning is True
    assert reason_morning == "OK"
    assert ok_lunch is False
    assert reason_lunch == "ENTRY_WINDOW_CLOSED"


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
        {"side": "BUY", "code": "AFFORD01", "qty": 20, "order_type": "best", "price": None}
    ]


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
