from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .interfaces import IndexChartAPI, TradingAPI
from .news_sentiment import NewsSentimentSignal
from .utils import compute_sma, match_name_to_sectors, parse_numeric

logger = logging.getLogger(__name__)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def industry_columns(code: str, industry_map: dict[str, Any]) -> dict[str, Any]:
    info = industry_map.get(str(code))
    if info is None:
        return {
            "industry_large_name": None,
            "industry_medium_name": None,
            "industry_small_name": None,
            "industry_bucket_code": None,
            "industry_bucket_name": None,
        }
    return {
        "industry_large_name": info.large_name,
        "industry_medium_name": info.medium_name,
        "industry_small_name": info.small_name,
        "industry_bucket_code": info.bucket_code or None,
        "industry_bucket_name": info.bucket_name or None,
    }


def resolve_sector_bucket_name(
    row: pd.Series,
    *,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: NewsSentimentSignal | None = None,
) -> str:
    industry_bucket = clean_text(row.get("industry_bucket_name"))
    if industry_bucket:
        return industry_bucket

    matched = match_name_to_sectors(str(row.get("name") or ""), sector_keywords)
    if not matched:
        return ""

    if news_signal is None:
        return sorted(matched)[0]

    ranked = sorted(
        matched,
        key=lambda sector: (float(news_signal.sector_scores.get(sector, 0.0)), str(sector)),
        reverse=True,
    )
    return str(ranked[0]) if ranked else ""


def enrich_industry_trend_fields(
    api: TradingAPI,
    df: pd.DataFrame,
    *,
    asof: str,
    lookback_bars: int,
    log_prefix: str,
) -> pd.DataFrame:
    if df is None or df.empty or not isinstance(api, IndexChartAPI):
        return df

    working = df.copy()
    for col in (
        "industry_bucket_code",
        "industry_close",
        "industry_ma5",
        "industry_ma20",
        "industry_day_change_pct",
        "industry_5d_change_pct",
    ):
        if col not in working.columns:
            working[col] = None

    bucket_codes = [
        clean_text(code).zfill(4)
        for code in working.get("industry_bucket_code", pd.Series(dtype=object)).tolist()
        if clean_text(code)
    ]
    if not bucket_codes:
        return working

    lookback = max(20, int(lookback_bars))
    snapshots: dict[str, dict[str, Any]] = {}
    for bucket_code in dict.fromkeys(bucket_codes):
        try:
            bars = api.daily_index_bars(bucket_code, end=asof, lookback=lookback)
        except Exception as exc:
            logger.warning(
                "%s industry index bars failed bucket_code=%s error=%s",
                log_prefix,
                bucket_code,
                exc,
            )
            continue
        snapshot = industry_trend_snapshot_from_bars(bars)
        if snapshot:
            snapshots[bucket_code] = snapshot

    if not snapshots:
        return working

    for idx, row in working.iterrows():
        bucket_code = clean_text(row.get("industry_bucket_code")).zfill(4)
        if not bucket_code:
            continue
        snapshot = snapshots.get(bucket_code)
        if not snapshot:
            continue
        for key, value in snapshot.items():
            working.at[idx, key] = value

    return working


def industry_trend_snapshot_from_bars(bars: pd.DataFrame) -> dict[str, Any]:
    if bars is None or bars.empty or "close" not in bars.columns:
        return {}

    close_s = pd.to_numeric(bars.get("close"), errors="coerce").dropna()
    if close_s.empty:
        return {}

    close = parse_numeric(close_s.iloc[-1])
    if close is None:
        return {}

    ma5 = compute_sma(close_s, 5).iloc[-1] if len(close_s) >= 5 else None
    ma20 = compute_sma(close_s, 20).iloc[-1] if len(close_s) >= 20 else None

    day_change_pct = None
    if len(close_s) >= 2:
        prev_close = parse_numeric(close_s.iloc[-2])
        if prev_close and prev_close > 0:
            day_change_pct = ((float(close) / float(prev_close)) - 1.0) * 100.0

    change_5d_pct = None
    if len(close_s) >= 6:
        base_close = parse_numeric(close_s.iloc[-6])
        if base_close and base_close > 0:
            change_5d_pct = ((float(close) / float(base_close)) - 1.0) * 100.0

    return {
        "industry_close": float(close),
        "industry_ma5": float(ma5) if ma5 is not None and not pd.isna(ma5) else None,
        "industry_ma20": float(ma20) if ma20 is not None and not pd.isna(ma20) else None,
        "industry_day_change_pct": day_change_pct,
        "industry_5d_change_pct": change_5d_pct,
    }
