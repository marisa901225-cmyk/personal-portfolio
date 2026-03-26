from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .utils import (
    compute_avg_value,
    compute_sma,
    is_etf_row,
    is_excluded_etf,
    normalize_code,
    parse_numeric,
    standardize_rank_df,
)

logger = logging.getLogger(__name__)

_MODEL_RELAXED_MIN_BARS = 60
_MODEL_RELAXED_MAX_PREMIUM_TO_MA20 = 0.15


def _rank_map(df: pd.DataFrame, rank_col: str) -> dict[str, int]:
    if df.empty or rank_col not in df.columns:
        return {}
    out: dict[str, int] = {}
    for _, row in df.iterrows():
        code = normalize_code(row.get("code"))
        rank = parse_numeric(row.get(rank_col))
        if code and rank is not None:
            out[code] = int(rank)
    return out


def _is_allowed_by_etf_policy(row: dict[str, Any], include_etf: bool) -> bool:
    if not include_etf and is_etf_row(row):
        return False
    if include_etf and is_etf_row(row) and is_excluded_etf(row):
        return False
    return True


def popular_screener(
    api: TradingAPI,
    asof: str,
    include_etf: bool = False,
    config: TradeEngineConfig | None = None,
) -> pd.DataFrame:
    cfg = config or TradeEngineConfig()
    vol_df = standardize_rank_df(
        api.volume_rank("volume", top_n=cfg.popular_volume_top_n, asof=asof),
        rank_key="volume_rank",
    )
    value_rank_df = standardize_rank_df(
        api.volume_rank("value", top_n=cfg.popular_value_candidate_top_n, asof=asof),
        rank_key="value_rank",
    )

    candidate_df = pd.concat([vol_df, value_rank_df], ignore_index=True)
    if candidate_df.empty:
        return _empty_popular_df()

    candidate_df = candidate_df.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)
    candidate_df = candidate_df[candidate_df.apply(lambda r: _is_allowed_by_etf_policy(r.to_dict(), include_etf), axis=1)]
    if candidate_df.empty:
        return _empty_popular_df()

    rows: list[dict[str, Any]] = []
    volume_rank_map = _rank_map(vol_df, "volume_rank")

    for _, row in candidate_df.iterrows():
        code = str(row["code"])
        try:
            bars = api.daily_bars(code=code, end=asof, lookback=10)
        except Exception as exc:
            logger.warning("popular_screener bars failed code=%s error=%s", code, exc)
            continue
        if bars is None or bars.empty:
            continue

        avg5, used_proxy = compute_avg_value(bars, window=5)
        if avg5 is None:
            continue
        close = parse_numeric(bars.iloc[-1].get("close")) if "close" in bars.columns else row.get("close")
        rows.append(
            {
                "code": code,
                "name": row.get("name", ""),
                "avg_value_5d": float(avg5),
                "used_value_proxy": bool(used_proxy),
                "asof_date": asof,
                "volume_rank": volume_rank_map.get(code),
                "value_rank_5d_top10": None,
                "close": close,
                "change_pct": parse_numeric(row.get("change_pct")),
                "is_etf": bool(row.get("is_etf", False) or is_etf_row(row)),
                "fallback_selected": False,
            }
        )

    if not rows:
        return _empty_popular_df()

    liquidity_df = pd.DataFrame(rows).sort_values("avg_value_5d", ascending=False).reset_index(drop=True)
    top_a = liquidity_df.head(cfg.popular_final_top_n).copy()
    top_a["value_rank_5d_top10"] = range(1, len(top_a) + 1)

    b_codes = set(vol_df["code"].astype(str)) if not vol_df.empty else set()
    inter = top_a[top_a["code"].astype(str).isin(b_codes)].copy()
    if inter.empty:
        fallback = liquidity_df[liquidity_df["code"].astype(str).isin(b_codes)].head(cfg.popular_final_top_n).copy()
        fallback["value_rank_5d_top10"] = range(1, len(fallback) + 1)
        fallback["fallback_selected"] = True
        out = fallback
    else:
        out = inter

    if out.empty:
        return _empty_popular_df()
    return _ensure_popular_columns(out)


def model_screener(
    api: TradingAPI,
    asof: str,
    include_etf: bool = False,
    config: TradeEngineConfig | None = None,
) -> pd.DataFrame:
    del include_etf  # model screener remains stock-centric by policy.

    cfg = config or TradeEngineConfig()
    mcap_df = standardize_rank_df(api.market_cap_rank(top_k=cfg.model_top_k, asof=asof), rank_key="mcap_rank")
    if mcap_df.empty:
        return _empty_model_df()

    has_numeric_mcap = mcap_df["mcap"].fillna(0).gt(0).any()
    if has_numeric_mcap:
        # Some KIS rank payloads omit market-cap numbers for otherwise valid large caps.
        # When that happens we trust the market-cap-ranked universe and keep those rows.
        mcap_df = mcap_df[
            (mcap_df["mcap"].fillna(0) >= cfg.model_mcap_min)
            | (mcap_df["mcap"].fillna(0) <= 0)
        ].copy()
    if mcap_df.empty:
        return _empty_model_df()

    mcap_df = mcap_df[~mcap_df.apply(lambda r: is_etf_row(r.to_dict()), axis=1)]
    if mcap_df.empty:
        return _empty_model_df()

    rows: list[dict[str, Any]] = []
    for _, row in mcap_df.iterrows():
        code = str(row["code"])
        mcap = parse_numeric(row.get("mcap"))
        if mcap is None:
            continue
        try:
            bars = api.daily_bars(code=code, end=asof, lookback=140)
        except Exception as exc:
            logger.warning("model_screener bars failed code=%s error=%s", code, exc)
            continue

        if bars is None or bars.empty or len(bars) < _MODEL_RELAXED_MIN_BARS:
            continue

        close_s = pd.to_numeric(bars.get("close"), errors="coerce")
        if close_s.dropna().empty:
            continue

        close = parse_numeric(close_s.iloc[-1])
        ma5 = compute_sma(close_s, 5).iloc[-1]
        ma20 = compute_sma(close_s, 20).iloc[-1]
        ma60 = compute_sma(close_s, 60).iloc[-1]
        ma120 = compute_sma(close_s, 120).iloc[-1] if len(close_s) >= 120 else None
        if close is None or pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
            continue

        avg20, used_proxy = compute_avg_value(bars, window=20)
        if avg20 is None:
            continue

        pass_liquidity = avg20 >= cfg.model_avg_value_20d_min
        pass_strict_ma = (
            ma120 is not None
            and not pd.isna(ma120)
            and (ma120 < ma60 < ma20 < ma5)
            and (close > ma5)
        )
        pass_relaxed_ma = (
            len(close_s) >= _MODEL_RELAXED_MIN_BARS
            and (close > ma20)
            and (ma20 > ma60)
            and (close <= ma20 * (1.0 + _MODEL_RELAXED_MAX_PREMIUM_TO_MA20))
        )
        trend_tier = "strict" if pass_strict_ma else "relaxed" if pass_relaxed_ma else ""
        if not (pass_liquidity and trend_tier):
            continue

        rows.append(
            {
                "code": code,
                "name": row.get("name", ""),
                "mcap": float(mcap) if mcap is not None else 0.0,
                "avg_value_20d": float(avg20),
                "ma5": float(ma5),
                "ma20": float(ma20),
                "ma60": float(ma60),
                "ma120": float(ma120) if ma120 is not None and not pd.isna(ma120) else None,
                "used_value_proxy": bool(used_proxy),
                "asof_date": asof,
                "close": close,
                "change_pct": parse_numeric(row.get("change_pct")),
                "is_etf": False,
                "trend_tier": trend_tier,
            }
        )

    if not rows:
        return _empty_model_df()
    out = pd.DataFrame(rows).sort_values("avg_value_20d", ascending=False).reset_index(drop=True)
    return _ensure_model_columns(out)


def etf_swing_screener(
    api: TradingAPI,
    asof: str,
    config: TradeEngineConfig | None = None,
) -> pd.DataFrame:
    cfg = config or TradeEngineConfig()

    vol_df = standardize_rank_df(
        api.volume_rank("volume", top_n=cfg.popular_volume_top_n, asof=asof),
        rank_key="volume_rank",
    )
    value_df = standardize_rank_df(
        api.volume_rank("value", top_n=cfg.popular_value_candidate_top_n, asof=asof),
        rank_key="value_rank",
    )
    base = pd.concat([vol_df, value_df], ignore_index=True)
    if base.empty:
        return _empty_etf_df()
    base = base.drop_duplicates(subset=["code"], keep="first")

    etf_only = base[base.apply(lambda r: is_etf_row(r.to_dict()), axis=1)].copy()
    if etf_only.empty:
        return _empty_etf_df()
    etf_only = etf_only[~etf_only.apply(lambda r: is_excluded_etf(r.to_dict()), axis=1)]
    if etf_only.empty:
        return _empty_etf_df()

    rows: list[dict[str, Any]] = []
    for _, row in etf_only.iterrows():
        code = str(row["code"])
        try:
            bars = api.daily_bars(code=code, end=asof, lookback=80)
        except Exception as exc:
            logger.warning("etf_swing_screener bars failed code=%s error=%s", code, exc)
            continue
        if bars is None or bars.empty or len(bars) < 60:
            continue

        close_s = pd.to_numeric(bars.get("close"), errors="coerce")
        ma5 = compute_sma(close_s, 5).iloc[-1]
        ma20 = compute_sma(close_s, 20).iloc[-1]
        ma60 = compute_sma(close_s, 60).iloc[-1]
        close = parse_numeric(close_s.iloc[-1])

        if close is None or pd.isna(ma5) or pd.isna(ma20) or pd.isna(ma60):
            continue

        avg20, used_proxy = compute_avg_value(bars, window=20)
        if avg20 is None or avg20 < cfg.swing_etf_min_avg_value_20d:
            continue

        trend_ok = (ma60 < ma20 < ma5) or (close > ma20)
        if not trend_ok:
            continue

        rows.append(
            {
                "code": code,
                "name": row.get("name", ""),
                "avg_value_20d": float(avg20),
                "ma5": float(ma5),
                "ma20": float(ma20),
                "ma60": float(ma60),
                "used_value_proxy": bool(used_proxy),
                "asof_date": asof,
                "close": close,
                "change_pct": parse_numeric(row.get("change_pct")),
                "is_etf": True,
            }
        )

    if not rows:
        return _empty_etf_df()
    out = pd.DataFrame(rows).sort_values("avg_value_20d", ascending=False).reset_index(drop=True)
    return _ensure_etf_columns(out)


def _ensure_popular_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "code",
        "name",
        "avg_value_5d",
        "used_value_proxy",
        "asof_date",
        "volume_rank",
        "value_rank_5d_top10",
        "close",
        "change_pct",
        "is_etf",
        "fallback_selected",
    ]
    for col in cols:
        if col not in df.columns:
            df[col] = None
    return df[cols].reset_index(drop=True)


def _ensure_model_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "code",
        "name",
        "mcap",
        "avg_value_20d",
        "ma5",
        "ma20",
        "ma60",
        "ma120",
        "used_value_proxy",
        "asof_date",
        "close",
        "change_pct",
        "is_etf",
        "trend_tier",
    ]
    for col in cols:
        if col not in df.columns:
            df[col] = None
    return df[cols].reset_index(drop=True)


def _ensure_etf_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "code",
        "name",
        "avg_value_20d",
        "ma5",
        "ma20",
        "ma60",
        "used_value_proxy",
        "asof_date",
        "close",
        "change_pct",
        "is_etf",
    ]
    for col in cols:
        if col not in df.columns:
            df[col] = None
    return df[cols].reset_index(drop=True)


def _empty_popular_df() -> pd.DataFrame:
    return _ensure_popular_columns(pd.DataFrame())


def _empty_model_df() -> pd.DataFrame:
    return _ensure_model_columns(pd.DataFrame())


def _empty_etf_df() -> pd.DataFrame:
    return _ensure_etf_columns(pd.DataFrame())
