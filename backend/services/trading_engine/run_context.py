from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import pandas as pd


@dataclass(slots=True)
class TradingRunMetrics:
    timings: dict[str, float] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    def incr(self, key: str, amount: int = 1) -> None:
        self.counters[key] = int(self.counters.get(key, 0)) + int(amount)

    def observe(self, key: str, value: float) -> None:
        self.timings[key] = float(value)

    def time_block(self, key: str) -> "_Timer":
        return _Timer(self, key)

    def as_log_fields(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in sorted(self.timings.items()):
            payload[key] = round(float(value), 4)
        for key, value in sorted(self.counters.items()):
            payload[key] = int(value)
        return payload


class _Timer:
    def __init__(self, metrics: TradingRunMetrics, key: str) -> None:
        self._metrics = metrics
        self._key = key
        self._started_at = 0.0

    def __enter__(self) -> "_Timer":
        self._started_at = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._metrics.observe(self._key, perf_counter() - self._started_at)


class CachedTradingAPI:
    def __init__(self, delegate: Any, *, metrics: TradingRunMetrics | None = None) -> None:
        self._delegate = delegate
        self._metrics = metrics
        self._daily_bars_cache: dict[tuple[str, str], tuple[int, pd.DataFrame]] = {}
        self._intraday_bars_cache: dict[tuple[str, str], tuple[int, pd.DataFrame]] = {}
        self._quote_cache: dict[str, dict[str, Any]] = {}
        self._volume_rank_cache: dict[tuple[str, str], tuple[int, list[dict[str, Any]]]] = {}
        self._hts_top_view_rank_cache: dict[str, tuple[int, list[dict[str, Any]]]] = {}
        self._market_cap_rank_cache: dict[str, tuple[int, list[dict[str, Any]]]] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
        cache_key = (str(code), str(end))
        requested_lookback = max(0, int(lookback))
        self._incr("daily_bars_requests")

        cached = self._daily_bars_cache.get(cache_key)
        if cached is not None:
            cached_lookback, cached_frame = cached
            if cached_lookback >= requested_lookback:
                self._incr("daily_bars_cache_hits")
                return _tail_frame(cached_frame, requested_lookback)

        self._incr("daily_bars_api_calls")
        bars = self._delegate.daily_bars(code=code, end=end, lookback=lookback)
        frame = bars.copy() if isinstance(bars, pd.DataFrame) else pd.DataFrame()
        existing = self._daily_bars_cache.get(cache_key)
        if existing is None or existing[0] <= requested_lookback:
            self._daily_bars_cache[cache_key] = (requested_lookback, frame.copy())
        return frame.copy()

    def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
        intraday_fn = getattr(self._delegate, "intraday_bars", None)
        if not callable(intraday_fn):
            raise AttributeError("intraday_bars")

        cache_key = (str(code), str(asof))
        requested_lookback = max(0, int(lookback))
        self._incr("intraday_bars_requests")

        cached = self._intraday_bars_cache.get(cache_key)
        if cached is not None:
            cached_lookback, cached_frame = cached
            if cached_lookback >= requested_lookback:
                self._incr("intraday_bars_cache_hits")
                return cached_frame.copy()

        self._incr("intraday_bars_api_calls")
        bars = intraday_fn(code=code, asof=asof, lookback=lookback)
        frame = bars.copy() if isinstance(bars, pd.DataFrame) else pd.DataFrame()
        existing = self._intraday_bars_cache.get(cache_key)
        if existing is None or existing[0] <= requested_lookback:
            self._intraday_bars_cache[cache_key] = (requested_lookback, frame.copy())
        return frame.copy()

    def quote(self, code: str) -> dict[str, Any]:
        normalized = str(code)
        self._incr("quote_requests")
        if normalized in self._quote_cache:
            self._incr("quote_cache_hits")
            return dict(self._quote_cache[normalized])

        self._incr("quote_api_calls")
        quote = self._delegate.quote(code)
        payload = dict(quote or {})
        self._quote_cache[normalized] = dict(payload)
        return payload

    def volume_rank(self, kind: str, top_n: int, asof: str) -> list[dict[str, Any]]:
        cache_key = (str(kind), str(asof))
        requested_top_n = max(0, int(top_n))
        self._incr("volume_rank_requests")

        cached = self._volume_rank_cache.get(cache_key)
        if cached is not None:
            cached_top_n, cached_rows = cached
            if cached_top_n >= requested_top_n:
                self._incr("volume_rank_cache_hits")
                return _copy_rank_rows(cached_rows, requested_top_n)

        self._incr("volume_rank_api_calls")
        rows = self._delegate.volume_rank(kind, top_n=top_n, asof=asof)
        payload = _normalize_rank_rows(rows)
        existing = self._volume_rank_cache.get(cache_key)
        if existing is None or existing[0] <= requested_top_n:
            self._volume_rank_cache[cache_key] = (requested_top_n, _copy_rank_rows(payload, 0))
        return _copy_rank_rows(payload, 0)

    def hts_top_view_rank(self, top_n: int, asof: str) -> list[dict[str, Any]]:
        hts_fn = getattr(self._delegate, "hts_top_view_rank", None)
        if not callable(hts_fn):
            raise AttributeError("hts_top_view_rank")

        cache_key = str(asof)
        requested_top_n = max(0, int(top_n))
        self._incr("hts_top_view_rank_requests")

        cached = self._hts_top_view_rank_cache.get(cache_key)
        if cached is not None:
            cached_top_n, cached_rows = cached
            if cached_top_n >= requested_top_n:
                self._incr("hts_top_view_rank_cache_hits")
                return _copy_rank_rows(cached_rows, requested_top_n)

        self._incr("hts_top_view_rank_api_calls")
        rows = hts_fn(top_n=top_n, asof=asof)
        payload = _normalize_rank_rows(rows)
        existing = self._hts_top_view_rank_cache.get(cache_key)
        if existing is None or existing[0] <= requested_top_n:
            self._hts_top_view_rank_cache[cache_key] = (requested_top_n, _copy_rank_rows(payload, 0))
        return _copy_rank_rows(payload, 0)

    def market_cap_rank(self, top_k: int, asof: str) -> list[dict[str, Any]]:
        cache_key = str(asof)
        requested_top_k = max(0, int(top_k))
        self._incr("market_cap_rank_requests")

        cached = self._market_cap_rank_cache.get(cache_key)
        if cached is not None:
            cached_top_k, cached_rows = cached
            if cached_top_k >= requested_top_k:
                self._incr("market_cap_rank_cache_hits")
                return _copy_rank_rows(cached_rows, requested_top_k)

        self._incr("market_cap_rank_api_calls")
        rows = self._delegate.market_cap_rank(top_k=top_k, asof=asof)
        payload = _normalize_rank_rows(rows)
        existing = self._market_cap_rank_cache.get(cache_key)
        if existing is None or existing[0] <= requested_top_k:
            self._market_cap_rank_cache[cache_key] = (requested_top_k, _copy_rank_rows(payload, 0))
        return _copy_rank_rows(payload, 0)

    def snapshot_counts(self) -> dict[str, int]:
        return {
            "daily_bars_cache_entries": len(self._daily_bars_cache),
            "intraday_bars_cache_entries": len(self._intraday_bars_cache),
            "quote_cache_entries": len(self._quote_cache),
            "volume_rank_cache_entries": len(self._volume_rank_cache),
            "hts_top_view_rank_cache_entries": len(self._hts_top_view_rank_cache),
            "market_cap_rank_cache_entries": len(self._market_cap_rank_cache),
        }

    def _incr(self, key: str, amount: int = 1) -> None:
        if self._metrics is not None:
            self._metrics.incr(key, amount)


def _tail_frame(frame: pd.DataFrame, lookback: int) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        return pd.DataFrame()
    if lookback <= 0 or frame.empty:
        return frame.copy()
    return frame.tail(lookback).copy()


def _normalize_rank_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _copy_rank_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected = rows[:limit] if limit > 0 else rows
    return [dict(row) for row in selected]
