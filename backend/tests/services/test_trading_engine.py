from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from backend.services.trading_engine.bot import HybridTradingBot
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.market_calendar import get_last_trading_day, is_trading_day
from backend.services.trading_engine.screeners import model_screener, popular_screener
from backend.services.trading_engine.state import PositionState


class FakeAPI:
    def __init__(self) -> None:
        self._volume_rank: dict[tuple[str, str], list[dict]] = {}
        self._market_cap_rank: dict[str, list[dict]] = {}
        self._bars: dict[tuple[str, str], pd.DataFrame] = {}
        self._quotes: dict[str, dict] = {}
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
        return []

    def cash_available(self) -> int:
        return 1_000_000

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
