from __future__ import annotations

import pandas as pd

from .config import TradeEngineConfig
from .news_sentiment import NewsSentimentSignal
from .strategy_theme import _diversify_candidate_rows_by_sector
from .types import QuoteMap
from .utils import parse_numeric


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


def _attach_popular_liquidity_signals(
    primary: pd.DataFrame,
    popular: pd.DataFrame,
) -> pd.DataFrame:
    if primary.empty or popular is None or popular.empty or "code" not in primary.columns or "code" not in popular.columns:
        return primary

    working = primary.copy()
    signal_cols = [
        "code",
        "value_rank",
        "volume_rank",
        "avg_value_5d",
        "change_pct",
        "legacy_top10_selected",
        "value_rank_5d_top10",
    ]
    existing_cols = [col for col in signal_cols if col in popular.columns]
    if "code" not in existing_cols:
        return working

    liquidity = popular[existing_cols].copy()
    if liquidity.empty:
        return working

    if "legacy_top10_selected" not in liquidity.columns:
        liquidity["legacy_top10_selected"] = False
    else:
        liquidity["legacy_top10_selected"] = liquidity["legacy_top10_selected"].map(_to_bool)

    sort_working = liquidity.copy()
    sort_working["_value_rank_5d_top10_num"] = (
        sort_working["value_rank_5d_top10"].map(parse_numeric)
        if "value_rank_5d_top10" in sort_working.columns
        else None
    )
    sort_working["_value_rank_num"] = (
        sort_working["value_rank"].map(parse_numeric)
        if "value_rank" in sort_working.columns
        else None
    )
    sort_working["_avg_value_5d_num"] = (
        sort_working["avg_value_5d"].map(parse_numeric)
        if "avg_value_5d" in sort_working.columns
        else None
    )
    sort_working["_change_pct_num"] = (
        sort_working["change_pct"].map(parse_numeric)
        if "change_pct" in sort_working.columns
        else None
    )
    sort_working["_volume_rank_num"] = (
        sort_working["volume_rank"].map(parse_numeric)
        if "volume_rank" in sort_working.columns
        else None
    )

    sort_working = sort_working.sort_values(
        by=[
            "legacy_top10_selected",
            "_value_rank_5d_top10_num",
            "_value_rank_num",
            "_avg_value_5d_num",
            "_change_pct_num",
            "_volume_rank_num",
            "code",
        ],
        ascending=[False, True, True, False, False, True, True],
        na_position="last",
    ).reset_index(drop=True)
    sort_working["popular_liquidity_rank"] = range(1, len(sort_working) + 1)

    merge_cols = [
        col
        for col in ("code", "legacy_top10_selected", "value_rank_5d_top10", "popular_liquidity_rank")
        if col in sort_working.columns
    ]
    if len(merge_cols) <= 1:
        return working

    return working.merge(sort_working[merge_cols], on="code", how="left")


def _resolve_day_max_change_pct(row: pd.Series, config: TradeEngineConfig) -> float:
    is_etf = _to_bool(row.get("_is_etf", row.get("is_etf", False)))
    base_cap = float(config.day_etf_max_change_pct if is_etf else config.day_max_change_pct)
    if is_etf:
        return base_cap

    live_change_pct = parse_numeric(row.get("_live_change_pct_num"))
    intraday_score = parse_numeric(row.get("_day_intraday_score"))
    if live_change_pct is None or intraday_score is None:
        return base_cap

    chase_cap = float(getattr(config, "day_momentum_chase_max_change_pct", base_cap))
    chase_score_min = float(getattr(config, "day_momentum_chase_min_intraday_score", 0.0))
    if (
        live_change_pct > base_cap
        and live_change_pct <= max(base_cap, chase_cap)
        and intraday_score >= chase_score_min
    ):
        return max(base_cap, chase_cap)
    return base_cap


def _resolve_candidate_price(row: pd.Series, quotes: QuoteMap) -> float | None:
    code = str(row.get("code") or "")
    quote = quotes.get(code, {}) if code else {}
    return (
        parse_numeric(quote.get("price"))
        or parse_numeric(row.get("price"))
        or parse_numeric(row.get("close"))
    )


def _resolve_day_entry_budget_cash(config: TradeEngineConfig) -> float:
    initial_capital = max(0.0, float(getattr(config, "initial_capital", 0.0)))
    day_cash_ratio = max(0.0, float(getattr(config, "day_cash_ratio", 0.0)))
    return initial_capital * day_cash_ratio


def _merge_candidates(
    popular: pd.DataFrame,
    model: pd.DataFrame,
    etf: pd.DataFrame,
    *,
    sector_keywords: dict[str, tuple[str, ...]] | None = None,
    news_signal: NewsSentimentSignal | None = None,
) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []

    if not popular.empty:
        p_cols = ["code", "name", "avg_value_5d", "close", "change_pct", "is_etf"]
        if "mcap" in popular.columns:
            p_cols.insert(2, "mcap")
        for extra_col in (
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
            "sector_bucket_selected",
            "legacy_top10_selected",
        ):
            if extra_col in popular.columns:
                p_cols.append(extra_col)
        p = popular[p_cols].copy()
        p["source_popular"] = True
        blocks.append(p)

    if not model.empty:
        m = model[["code", "name", "avg_value_20d", "ma20", "ma60", "close", "change_pct", "is_etf"]].copy()
        m["source_model"] = True
        blocks.append(m)

    if not etf.empty:
        e = etf[["code", "name", "avg_value_20d", "ma20", "ma60", "close", "change_pct", "is_etf"]].copy()
        e["source_etf"] = True
        blocks.append(e)

    if not blocks:
        return pd.DataFrame(columns=["code"])

    merged = pd.concat(blocks, ignore_index=True, sort=False)
    if "theme_injected" not in merged.columns:
        merged["theme_injected"] = False
    merged["theme_injected"] = merged["theme_injected"].map(_to_bool)
    merged["_liquidity_score"] = merged.apply(
        lambda row: max(
            parse_numeric(row.get("avg_value_20d")) or 0.0,
            parse_numeric(row.get("avg_value_5d")) or 0.0,
        ),
        axis=1,
    )
    sort_cols = ["theme_injected", "_liquidity_score"]
    sort_cols.extend(col for col in ("avg_value_20d", "avg_value_5d") if col in merged.columns)
    merged = merged.sort_values(
        by=sort_cols,
        ascending=[False] * len(sort_cols),
        na_position="last",
    )
    merged = merged.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)
    merged = _diversify_candidate_rows_by_sector(
        merged,
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )
    return merged.drop(columns=["_liquidity_score"], errors="ignore")
