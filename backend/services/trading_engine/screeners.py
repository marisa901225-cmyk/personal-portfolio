from __future__ import annotations

from datetime import datetime, timedelta
import logging
from time import perf_counter
from typing import Any

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
_SWING_MA200_MIN_BARS = 200


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

            ma200_setup = _resolve_swing_ma200_setup(
                api,
                code=code,
                asof=asof,
                initial_bars=bars,
                config=cfg,
            )
            if ma200_setup is not None and not bool(ma200_setup.get("swing_ma200_setup")):
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
                    **(ma200_setup or {}),
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


def _resolve_swing_ma200_setup(
    api: TradingAPI,
    *,
    code: str,
    asof: str,
    initial_bars: pd.DataFrame,
    config: TradeEngineConfig,
) -> dict[str, Any] | None:
    watch_codes = {
        str(item).strip()
        for item in getattr(config, "swing_ma200_watch_codes", ())
        if str(item).strip()
    }
    if str(code) not in watch_codes:
        return None

    bars = _load_deep_daily_bars(
        api,
        code=code,
        end=asof,
        min_bars=_SWING_MA200_MIN_BARS,
        initial_bars=initial_bars,
    )
    if bars.empty or len(bars) < _SWING_MA200_MIN_BARS or "close" not in bars.columns:
        return {"swing_ma200_setup": False, "swing_ma200_reason": "insufficient_bars"}

    working = bars.copy()
    working["close"] = pd.to_numeric(working["close"], errors="coerce")
    working = working.dropna(subset=["close"])
    if len(working) < _SWING_MA200_MIN_BARS:
        return {"swing_ma200_setup": False, "swing_ma200_reason": "insufficient_close"}

    working["ma200"] = working["close"].rolling(_SWING_MA200_MIN_BARS).mean()
    valid = working.dropna(subset=["ma200"])
    if valid.empty:
        return {"swing_ma200_setup": False, "swing_ma200_reason": "missing_ma200"}

    latest = valid.iloc[-1]
    ma200 = parse_numeric(latest.get("ma200"))
    close = parse_numeric(latest.get("close"))
    if ma200 is None or ma200 <= 0 or close is None:
        return {"swing_ma200_setup": False, "swing_ma200_reason": "invalid_ma200"}

    lookback = max(1, int(getattr(config, "swing_ma200_touch_lookback_bars", 3)))
    tolerance = max(0.0, float(getattr(config, "swing_ma200_touch_tolerance_pct", 1.0))) / 100.0
    recent = valid.tail(lookback)
    touched = False
    for _, row in recent.iterrows():
        row_ma200 = parse_numeric(row.get("ma200"))
        if row_ma200 is None or row_ma200 <= 0:
            continue
        low = parse_numeric(row.get("low")) or parse_numeric(row.get("close"))
        high = parse_numeric(row.get("high")) or parse_numeric(row.get("close"))
        if low is None or high is None:
            continue
        if low <= row_ma200 * (1.0 + tolerance) and high >= row_ma200 * (1.0 - tolerance):
            touched = True
            break

    distance_pct = ((float(close) / float(ma200)) - 1.0) * 100.0
    max_distance_pct = float(getattr(config, "swing_ma200_max_distance_pct", 8.0))
    setup = touched and distance_pct <= max_distance_pct
    return {
        "swing_ma200_setup": bool(setup),
        "swing_ma200_recent_touch": bool(touched),
        "swing_ma200": float(ma200),
        "swing_ma200_distance_pct": float(distance_pct),
        "swing_ma200_reason": "ok" if setup else "not_near_ma200",
    }


def _load_deep_daily_bars(
    api: TradingAPI,
    *,
    code: str,
    end: str,
    min_bars: int,
    initial_bars: pd.DataFrame,
) -> pd.DataFrame:
    frames = [initial_bars] if initial_bars is not None and not initial_bars.empty else []
    seen_ends = {str(end)}
    current_end = _previous_calendar_day_from_frame(initial_bars, fallback=end)

    while sum(len(frame) for frame in frames) < min_bars and current_end and current_end not in seen_ends:
        seen_ends.add(current_end)
        try:
            frame = api.daily_bars(code=code, end=current_end, lookback=100)
        except Exception as exc:
            logger.warning("swing ma200 deep bars failed code=%s end=%s error=%s", code, current_end, exc)
            break
        if frame is None or frame.empty:
            break
        frames.append(frame)
        next_end = _previous_calendar_day_from_frame(frame, fallback=current_end)
        if not next_end or next_end in seen_ends:
            break
        current_end = next_end

    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True, sort=False)
    if "date" not in merged.columns:
        return merged.tail(min_bars).reset_index(drop=True)
    return (
        merged.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .tail(max(min_bars, len(merged)))
        .reset_index(drop=True)
    )


def _previous_calendar_day_from_frame(frame: pd.DataFrame, *, fallback: str) -> str:
    date_value = None
    if frame is not None and not frame.empty and "date" in frame.columns:
        dates = frame["date"].dropna().astype(str)
        if not dates.empty:
            date_value = dates.min()
    if not date_value:
        date_value = str(fallback)
    try:
        return (datetime.strptime(str(date_value), "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    except ValueError:
        return ""


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
        "swing_ma200_setup",
        "swing_ma200_recent_touch",
        "swing_ma200",
        "swing_ma200_distance_pct",
        "swing_ma200_reason",
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
