from __future__ import annotations

from datetime import datetime, timedelta
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.models_misc import (
    TradingEngineIndustrySyncState,
    TradingEngineStockIndustry,
)
from backend.services.trading_engine.bot import HybridTradingBot
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.day_chart_review import (
    DayChartReviewResult,
    review_day_candidates_with_llm,
)
from backend.services.trading_engine.execution import exit_position
from backend.services.trading_engine.industry_master import (
    StockIndustryInfo,
    load_stock_industry_db_map,
    resolve_stock_industry_info,
)
from backend.services.trading_engine.news_sentiment import NewsSentimentSignal
from backend.services.trading_engine.regime import detect_intraday_circuit_breaker, get_regime
from backend.services.trading_engine.risk import can_enter, should_exit_position
from backend.services.trading_engine.runtime import _load_config_from_env, get_last_trading_day, is_trading_day
from backend.services.trading_engine.screeners import etf_swing_screener, model_screener, popular_screener
from backend.services.trading_engine.state import (
    PositionState,
    get_day_reentry_blocked_codes,
    get_day_stoploss_fail_count,
    get_day_stoploss_codes_today,
    get_day_stoploss_excluded_codes,
    get_swing_time_excluded_codes,
    load_state,
    mark_day_stoploss_today,
    new_state,
    record_day_stoploss_failure,
    save_state,
)
from backend.services.trading_engine.stock_master import StockMasterInfo, load_swing_universe_candidates
from backend.services.trading_engine.strategy import Candidates, pick_swing, rank_daytrade_codes


class FakeAPI:
    def __init__(self) -> None:
        self._volume_rank: dict[tuple[str, str], list[dict]] = {}
        self._hts_top_view_rank: dict[str, list[dict]] = {}
        self._market_cap_rank: dict[str, list[dict]] = {}
        self._bars: dict[tuple[str, str], pd.DataFrame] = {}
        self._index_bars: dict[tuple[str, str], pd.DataFrame] = {}
        self._quotes: dict[str, dict] = {}
        self._positions: list[dict] = []
        self._cash_available: int = 1_000_000
        self.order_calls: list[dict] = []

    def volume_rank(self, kind: str, top_n: int, asof: str) -> list[dict]:
        del top_n
        return list(self._volume_rank.get((kind, asof), []))

    def hts_top_view_rank(self, top_n: int, asof: str) -> list[dict]:
        del top_n
        return list(self._hts_top_view_rank.get(asof, []))

    def market_cap_rank(self, top_k: int, asof: str) -> list[dict]:
        del top_k
        return list(self._market_cap_rank.get(asof, []))

    def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
        del lookback
        return self._bars.get((code, end), pd.DataFrame())

    def daily_index_bars(self, index_code: str, end: str, lookback: int) -> pd.DataFrame:
        del lookback
        return self._index_bars.get((index_code, end), pd.DataFrame())

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
        return {
            "order_id": f"{side}-{code}",
            "filled_qty": qty,
            "avg_price": price or self.quote(code).get("price", 0),
        }

    def open_orders(self) -> list[dict]:
        return []

    def cancel_order(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": "cancelled"}


class _ChartReviewLLMStub:
    def __init__(
        self,
        *,
        local_raw: str = "",
        paid_raw: str = "",
        remote_configured: bool = True,
        paid_configured: bool = True,
    ) -> None:
        self.settings = SimpleNamespace(
            is_remote_configured=lambda: remote_configured,
            is_paid_configured=lambda: paid_configured,
        )
        self.paid_backend = object() if paid_configured else None
        self.local_raw = local_raw
        self.paid_raw = paid_raw
        self.local_calls: list[dict] = []
        self.paid_calls: list[dict] = []

    def generate_chat(self, messages, **kwargs):
        self.local_calls.append({"messages": messages, "kwargs": kwargs})
        return self.local_raw

    def generate_paid_chat(self, messages, **kwargs):
        self.paid_calls.append({"messages": messages, "kwargs": kwargs})
        return self.paid_raw


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


def _make_chart_review_candidates(asof: str) -> Candidates:
    return Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "PASS01", "name": "Pass 01"},
                {"code": "KEEP01", "name": "Keep 01"},
                {"code": "NEXT01", "name": "Next 01"},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )


def _write_idx_master_zip(path, rows: dict[str, str]) -> None:
    payload = "\n".join(f"0{code}{name}" for code, name in rows.items())
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("idxcode.mst", payload.encode("cp949"))


def _write_stock_master_zip(path, *, member_name: str, tail_width: int, rows: list[tuple[str, str, str, str, str]]) -> None:
    payload_rows: list[str] = []
    for code, name, large_code, medium_code, small_code in rows:
        prefix = f"{code:<9}{'':12}{name}"
        suffix = f"000{large_code}{medium_code}{small_code}".ljust(tail_width, "0")
        payload_rows.append(prefix + suffix)
    payload = "\n".join(payload_rows)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member_name, payload.encode("cp949"))


__all__ = [
    "datetime",
    "timedelta",
    "json",
    "SimpleNamespace",
    "patch",
    "pd",
    "create_engine",
    "select",
    "sessionmaker",
    "TradingEngineIndustrySyncState",
    "TradingEngineStockIndustry",
    "HybridTradingBot",
    "TradeEngineConfig",
    "DayChartReviewResult",
    "review_day_candidates_with_llm",
    "exit_position",
    "StockIndustryInfo",
    "load_stock_industry_db_map",
    "resolve_stock_industry_info",
    "get_last_trading_day",
    "is_trading_day",
    "NewsSentimentSignal",
    "detect_intraday_circuit_breaker",
    "get_regime",
    "can_enter",
    "should_exit_position",
    "_load_config_from_env",
    "StockMasterInfo",
    "load_swing_universe_candidates",
    "Candidates",
    "pick_swing",
    "rank_daytrade_codes",
    "etf_swing_screener",
    "model_screener",
    "popular_screener",
    "PositionState",
    "get_day_reentry_blocked_codes",
    "get_day_stoploss_fail_count",
    "get_day_stoploss_codes_today",
    "get_day_stoploss_excluded_codes",
    "get_swing_time_excluded_codes",
    "load_state",
    "mark_day_stoploss_today",
    "new_state",
    "record_day_stoploss_failure",
    "save_state",
    "FakeAPI",
    "_ChartReviewLLMStub",
    "_make_bars",
    "_make_bars_from_closes",
    "_make_intraday_bars",
    "_make_chart_review_candidates",
    "_write_idx_master_zip",
    "_write_stock_master_zip",
]
