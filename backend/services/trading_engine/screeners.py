from __future__ import annotations

import logging
from time import perf_counter

import pandas as pd

from .config import TradeEngineConfig
from .industry_trend import enrich_industry_trend_fields, industry_columns
from .industry_master import load_stock_industry_db_map
from .interfaces import TradingAPI
from .news_sentiment import NewsSentimentSignal
from .run_context import TradingRunMetrics
from .screener_collectors import (
    _combine_popular_rows,
    _enrich_model_quote_fields,
    _enrich_popular_industry_trend_fields,
    _enrich_popular_quote_fields,
    _inject_theme_candidates,
    _popular_sector_keywords,
    _rank_map,
    _select_legacy_popular_rows,
    _select_sector_bucket_rows,
)
from .stock_master import load_stock_master_map, load_swing_universe_candidates
from .utils import (
    compute_avg_value,
    compute_sma,
    is_broad_market_etf,
    is_etf_row,
    is_excluded_etf,
    is_live_status_disqualified,
    parse_numeric,
    standardize_rank_df,
)

logger = logging.getLogger(__name__)

_MODEL_RELAXED_MIN_BARS = 60
_MODEL_RELAXED_MAX_PREMIUM_TO_MA20 = 0.15


def popular_screener(
    api: TradingAPI,
    asof: str,
    include_etf: bool = False,
    config: TradeEngineConfig | None = None,
    news_signal: NewsSentimentSignal | None = None,
    metrics: TradingRunMetrics | None = None,
) -> pd.DataFrame:
    started_at = perf_counter()
    cfg = config or TradeEngineConfig()
    try:
        vol_df = standardize_rank_df(
            api.volume_rank("volume", top_n=cfg.popular_volume_top_n, asof=asof),
            rank_key="volume_rank",
        )
        value_rank_df = standardize_rank_df(
            api.volume_rank("value", top_n=cfg.popular_value_candidate_top_n, asof=asof),
            rank_key="value_rank",
        )
        hts_view_rank_map: dict[str, int] = {}
        hts_top_view_fn = getattr(api, "hts_top_view_rank", None)
        if callable(hts_top_view_fn) and int(getattr(cfg, "day_hts_top_view_top_n", 0)) > 0:
            hts_view_df = standardize_rank_df(
                hts_top_view_fn(top_n=cfg.day_hts_top_view_top_n, asof=asof),
                rank_key="hts_view_rank",
            )
            hts_view_rank_map = _rank_map(hts_view_df, "hts_view_rank")

        candidate_df = pd.concat([vol_df, value_rank_df], ignore_index=True)
        if candidate_df.empty:
            return _empty_popular_df()

        candidate_df = candidate_df.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)
        candidate_df = candidate_df[candidate_df.apply(lambda r: _is_allowed_by_etf_policy(r.to_dict(), include_etf), axis=1)]
        if candidate_df.empty:
            return _empty_popular_df()

        rows: list[dict[str, object]] = []
        volume_rank_map = _rank_map(vol_df, "volume_rank")
        value_rank_map = _rank_map(value_rank_df, "value_rank")
        stock_master_map = load_stock_master_map(
            kospi_master_path=cfg.industry_kospi_master_path,
            kosdaq_master_path=cfg.industry_kosdaq_master_path,
        )
        industry_map = load_stock_industry_db_map(
            idxcode_path=cfg.industry_idx_master_path,
            kospi_master_path=cfg.industry_kospi_master_path,
            kosdaq_master_path=cfg.industry_kosdaq_master_path,
        )

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
            recent_high_10d = None
            retrace_from_high_10d_pct = None
            breakout_vs_prev_high_10d_pct = None
            if "close" in bars.columns:
                close_s = pd.to_numeric(bars.get("close"), errors="coerce")
                if not close_s.dropna().empty:
                    recent_high_10d = parse_numeric(close_s.max())
                    if close is not None and recent_high_10d and recent_high_10d > 0:
                        retrace_from_high_10d_pct = ((float(close) / float(recent_high_10d)) - 1.0) * 100.0
                    prev_close_s = close_s.iloc[:-1].dropna()
                    if close is not None and not prev_close_s.empty:
                        prev_high_10d = parse_numeric(prev_close_s.max())
                        if prev_high_10d and prev_high_10d > 0:
                            breakout_vs_prev_high_10d_pct = ((float(close) / float(prev_high_10d)) - 1.0) * 100.0
            rows.append(
                {
                    "code": code,
                    "name": row.get("name", ""),
                    "mcap": parse_numeric(row.get("mcap")),
                    "avg_value_5d": float(avg5),
                    "used_value_proxy": bool(used_proxy),
                    "asof_date": asof,
                    "volume_rank": volume_rank_map.get(code),
                    "value_rank": value_rank_map.get(code),
                    "hts_view_rank": hts_view_rank_map.get(code),
                    "master_market": (
                        stock_master_map.get(code).market
                        if code in stock_master_map
                        else None
                    ),
                    "value_rank_5d_top10": None,
                    "close": close,
                    "change_pct": parse_numeric(row.get("change_pct")),
                    "is_etf": bool(row.get("is_etf", False) or is_etf_row(row)),
                    "fallback_selected": False,
                    "theme_injected": False,
                    "theme_sector": None,
                    "retrace_from_high_10d_pct": retrace_from_high_10d_pct,
                    "breakout_vs_prev_high_10d_pct": breakout_vs_prev_high_10d_pct,
                    **industry_columns(code, industry_map),
                }
            )

        if not rows:
            return _empty_popular_df()

        liquidity_df = pd.DataFrame(rows).sort_values("avg_value_5d", ascending=False).reset_index(drop=True)

        sector_keywords = _popular_sector_keywords(cfg, news_signal)
        sector_bucket = _select_sector_bucket_rows(
            liquidity_df,
            sector_keywords=sector_keywords,
            per_sector_top_n=cfg.popular_sector_top_n,
            news_signal=news_signal,
        )
        legacy_top = _select_legacy_popular_rows(
            liquidity_df,
            volume_df=vol_df,
            top_n=cfg.popular_final_top_n,
        )
        out = _combine_popular_rows(sector_bucket, legacy_top)

        out = _inject_theme_candidates(out, liquidity_df, news_signal, cfg)
        if out.empty:
            return _empty_popular_df()
        out = _enrich_popular_industry_trend_fields(api, out, asof=asof, config=cfg)
        out = _enrich_popular_quote_fields(api, out)
        out = _apply_live_status_filter(out)
        if out.empty:
            return _empty_popular_df()
        out = _apply_day_stock_quality_floor(out, cfg)
        if out.empty:
            return _empty_popular_df()
        return _ensure_popular_columns(out)
    finally:
        if metrics is not None:
            metrics.observe("popular_screener_s", perf_counter() - started_at)


def model_screener(
    api: TradingAPI,
    asof: str,
    include_etf: bool = False,
    config: TradeEngineConfig | None = None,
    metrics: TradingRunMetrics | None = None,
) -> pd.DataFrame:
    started_at = perf_counter()
    del include_etf

    try:
        cfg = config or TradeEngineConfig()
        universe_rows = load_swing_universe_candidates(cfg)
        if universe_rows:
            mcap_df = pd.DataFrame(universe_rows)
        else:
            mcap_df = standardize_rank_df(api.market_cap_rank(top_k=cfg.model_top_k, asof=asof), rank_key="mcap_rank")
            if mcap_df.empty:
                return _empty_model_df()

            has_numeric_mcap = mcap_df["mcap"].fillna(0).gt(0).any()
            if has_numeric_mcap:
                mcap_df = mcap_df[
                    (mcap_df["mcap"].fillna(0) >= cfg.model_mcap_min)
                    | (mcap_df["mcap"].fillna(0) <= 0)
                ].copy()
        if mcap_df.empty:
            return _empty_model_df()

        mcap_df = mcap_df[~mcap_df.apply(lambda r: is_etf_row(r.to_dict()), axis=1)]
        if mcap_df.empty:
            return _empty_model_df()

        industry_map = load_stock_industry_db_map(
            idxcode_path=cfg.industry_idx_master_path,
            kospi_master_path=cfg.industry_kospi_master_path,
            kosdaq_master_path=cfg.industry_kosdaq_master_path,
        )

        rows: list[dict[str, object]] = []
        for _, row in mcap_df.iterrows():
            code = str(row["code"])
            mcap = parse_numeric(row.get("mcap")) or parse_numeric(row.get("master_market_cap"))
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
                    "master_is_index_member": bool(row.get("master_is_index_member", False)),
                    **industry_columns(code, industry_map),
                }
            )

        if not rows:
            return _empty_model_df()
        out = pd.DataFrame(rows).sort_values(
            by=["master_is_index_member", "avg_value_20d", "mcap"],
            ascending=[False, False, False],
            na_position="last",
        ).reset_index(drop=True)
        out = enrich_industry_trend_fields(
            api,
            out,
            asof=asof,
            lookback_bars=cfg.swing_industry_lookback_bars,
            log_prefix="model_screener",
        )
        out = _enrich_model_quote_fields(api, out)
        out = _apply_live_status_filter(out)
        if out.empty:
            return _empty_model_df()
        return _ensure_model_columns(out)
    finally:
        if metrics is not None:
            metrics.observe("model_screener_s", perf_counter() - started_at)


def etf_swing_screener(
    api: TradingAPI,
    asof: str,
    config: TradeEngineConfig | None = None,
    metrics: TradingRunMetrics | None = None,
) -> pd.DataFrame:
    started_at = perf_counter()
    try:
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
        etf_only = etf_only[
            ~etf_only.apply(
                lambda r: is_excluded_etf(r.to_dict()) or is_broad_market_etf(r.to_dict()),
                axis=1,
            )
        ]
        if etf_only.empty:
            return _empty_etf_df()

        rows: list[dict[str, object]] = []
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
    finally:
        if metrics is not None:
            metrics.observe("etf_swing_screener_s", perf_counter() - started_at)


def _is_allowed_by_etf_policy(row: dict[str, object], include_etf: bool) -> bool:
    if not include_etf and is_etf_row(row):
        return False
    if include_etf and is_etf_row(row) and is_excluded_etf(row):
        return False
    return True


def _apply_live_status_filter(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    working = df.copy()
    keep_mask = ~working.apply(is_live_status_disqualified, axis=1)
    return working.loc[keep_mask].reset_index(drop=True)


def _apply_day_stock_quality_floor(
    df: pd.DataFrame,
    config: TradeEngineConfig,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    working = df.copy()
    if "is_etf" not in working.columns:
        working["is_etf"] = False
    if "mcap" not in working.columns:
        working["mcap"] = None

    stock_mask = ~working["is_etf"].fillna(False).map(bool)
    if not stock_mask.any():
        return working.reset_index(drop=True)

    avg_value_ok = working["avg_value_5d"].fillna(0) >= float(config.day_stock_min_avg_value_5d)
    mcap_series = pd.to_numeric(working["mcap"], errors="coerce").fillna(0)
    stock_has_mcap = bool((stock_mask & mcap_series.gt(0)).any())
    mcap_ok = mcap_series >= float(config.day_stock_min_mcap) if stock_has_mcap else True
    keep_mask = (~stock_mask) | (avg_value_ok & mcap_ok)
    return working.loc[keep_mask].reset_index(drop=True)


def _ensure_popular_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "code",
        "name",
        "mcap",
        "avg_value_5d",
        "used_value_proxy",
        "asof_date",
        "volume_rank",
        "value_rank",
        "hts_view_rank",
        "master_market",
        "value_rank_5d_top10",
        "close",
        "change_pct",
        "is_etf",
        "fallback_selected",
        "sector_bucket_selected",
        "legacy_top10_selected",
        "theme_injected",
        "theme_sector",
        "industry_large_name",
        "industry_medium_name",
        "industry_small_name",
        "industry_bucket_code",
        "industry_bucket_name",
        "industry_close",
        "industry_ma5",
        "industry_ma20",
        "industry_day_change_pct",
        "industry_5d_change_pct",
        "market_warning_code",
        "management_issue_code",
        "retrace_from_high_10d_pct",
        "breakout_vs_prev_high_10d_pct",
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
        "industry_large_name",
        "industry_medium_name",
        "industry_small_name",
        "industry_bucket_code",
        "industry_bucket_name",
        "industry_close",
        "industry_ma5",
        "industry_ma20",
        "industry_day_change_pct",
        "industry_5d_change_pct",
        "market_warning_code",
        "management_issue_code",
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
