from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass

import pandas as pd

from .candidate_scoring import (
    _day_intraday_structure_score,
    _resolve_change_pct,
    _score_day_row,
    _score_swing_row,
    _swing_quote_structure_score,
)
from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .news_sentiment import NewsSentimentSignal, _load_sector_keywords
from .screeners import etf_swing_screener, model_screener, popular_screener
from .types import QuoteMap
from .utils import is_broad_market_etf, is_live_status_disqualified, match_name_to_sectors, parse_numeric

_PREFERRED_THEME_ETF_NAME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "semiconductor": ("kodex 반도체",),
}


@dataclass(slots=True)
class Candidates:
    asof: str
    popular: pd.DataFrame
    model: pd.DataFrame
    etf: pd.DataFrame
    merged: pd.DataFrame
    quote_codes: list[str]



def build_candidates(
    api: TradingAPI,
    asof: str,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> Candidates:
    excluded_codes = _proxy_codes(config)
    popular = _drop_excluded_codes(
        popular_screener(
            api,
            asof,
            include_etf=config.include_etf,
            config=config,
            news_signal=news_signal,
        ),
        excluded_codes,
    )
    model = _drop_excluded_codes(
        model_screener(api, asof, include_etf=False, config=config),
        excluded_codes,
    )
    etf = (
        _drop_excluded_codes(etf_swing_screener(api, asof, config=config), excluded_codes)
        if config.include_etf
        else pd.DataFrame()
    )

    sector_keywords = _candidate_sector_keywords(config, news_signal)
    merged = _merge_candidates(
        popular,
        model,
        etf,
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )
    merged = _drop_excluded_codes(merged, excluded_codes)
    quote_codes = _build_quote_codes(merged, config.quote_score_limit)
    return Candidates(
        asof=asof,
        popular=popular,
        model=model,
        etf=etf,
        merged=merged,
        quote_codes=quote_codes,
    )


def exclude_candidate_codes(candidates: Candidates, excluded_codes: set[str]) -> Candidates:
    if not excluded_codes:
        return candidates

    return Candidates(
        asof=candidates.asof,
        popular=_drop_excluded_codes(candidates.popular, excluded_codes),
        model=_drop_excluded_codes(candidates.model, excluded_codes),
        etf=_drop_excluded_codes(candidates.etf, excluded_codes),
        merged=_drop_excluded_codes(candidates.merged, excluded_codes),
        quote_codes=[str(code) for code in candidates.quote_codes if str(code) not in excluded_codes],
    )


def fetch_quotes_subset(api: TradingAPI, codes: list[str]) -> QuoteMap:
    out: QuoteMap = {}
    for code in codes:
        try:
            out[code] = api.quote(code)
        except Exception:
            continue
    return out


def pick_swing(
    candidates: Candidates,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> str | None:
    ranked_codes = rank_swing_codes(candidates, quotes, config, news_signal=news_signal)
    return ranked_codes[0] if ranked_codes else None


def rank_swing_codes(
    candidates: Candidates,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> list[str]:
    primary = candidates.model.copy()
    use_etf_fallback = primary.empty and config.allow_etf_swing_fallback
    if primary.empty and not use_etf_fallback:
        return []

    if use_etf_fallback:
        primary = candidates.etf.copy()
        if primary.empty:
            return []
        primary["source_model"] = False
    else:
        primary["source_model"] = True

    if primary.empty:
        return []

    primary = _attach_popular_liquidity_signals(primary, candidates.popular)

    if "is_etf" in primary.columns and primary["is_etf"].fillna(False).any():
        primary = primary[~primary.apply(lambda r: is_broad_market_etf(r.to_dict()), axis=1)]
        if primary.empty:
            return []

    primary["_change_pct_num"] = primary.apply(lambda r: _resolve_change_pct(r, quotes), axis=1)
    primary = primary[
        primary["_change_pct_num"].isna()
        | (primary["_change_pct_num"] > float(config.swing_hard_drop_exclude_pct))
    ]
    if primary.empty:
        return []

    if use_etf_fallback:
        primary = primary[
            primary["_change_pct_num"].isna()
            | (primary["_change_pct_num"] >= float(config.swing_etf_fallback_min_change_pct))
        ]
        if primary.empty:
            return []

    scored = primary.copy()
    if news_signal is None:
        scored["score"] = scored.apply(lambda r: _score_swing_row(r, quotes, config), axis=1)
    else:
        scored["score"] = scored.apply(lambda r: _score_swing_row(r, quotes, config, news_signal), axis=1)
    scored = scored.sort_values("score", ascending=False)
    if scored.empty:
        return []

    ordered_codes = [str(code) for code in scored["code"].tolist()]

    if not use_etf_fallback:
        themed_etf_code = _pick_theme_day_swing_etf(
            stock_scored=scored,
            etf_candidates=candidates.etf,
            quotes=quotes,
            config=config,
            news_signal=news_signal,
        )
        if themed_etf_code:
            ordered_codes = [str(themed_etf_code)] + [code for code in ordered_codes if str(code) != str(themed_etf_code)]

    deduped_codes: list[str] = []
    seen: set[str] = set()
    for code in ordered_codes:
        code_str = str(code or "").strip()
        if not code_str or code_str in seen:
            continue
        seen.add(code_str)
        deduped_codes.append(code_str)
    return deduped_codes


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


def pick_daytrade(
    candidates: Candidates,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> str | None:
    ranked_codes = rank_daytrade_codes(candidates, quotes, config, news_signal=news_signal)
    return ranked_codes[0] if ranked_codes else None


def rank_daytrade_codes(
    candidates: Candidates,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> list[str]:
    pool = candidates.popular.copy()
    if pool.empty:
        return []

    if "is_etf" not in pool.columns:
        pool["is_etf"] = False
    pool["_is_etf"] = pool["is_etf"].map(_to_bool)
    pool["_avg_value_5d_num"] = (
        pool["avg_value_5d"].map(parse_numeric)
        if "avg_value_5d" in pool.columns
        else 0.0
    )
    pool["_mcap_num"] = (
        pool["mcap"].map(parse_numeric)
        if "mcap" in pool.columns
        else 0.0
    )
    pool["_change_pct_num"] = (
        pool["change_pct"].map(parse_numeric)
        if "change_pct" in pool.columns
        else None
    )
    pool["_retrace_from_high_10d_pct"] = (
        pool["retrace_from_high_10d_pct"].map(parse_numeric)
        if "retrace_from_high_10d_pct" in pool.columns
        else None
    )
    pool["_market_warning_code"] = pool.apply(lambda r: _resolve_market_warning_code(r, quotes), axis=1)
    pool["_management_issue_code"] = pool.apply(lambda r: _resolve_management_issue_code(r, quotes), axis=1)
    pool["_day_price_num"] = pool.apply(lambda r: _resolve_candidate_price(r, quotes), axis=1)
    max_day_entry_price = _resolve_day_entry_budget_cash(config)
    if max_day_entry_price > 0:
        pool = pool[
            pool["_day_price_num"].isna()
            | (pool["_day_price_num"] <= max_day_entry_price)
        ]
        if pool.empty:
            return []

    if config.include_etf:
        pool = pool[
            (~pool["_is_etf"])
            | (pool["_avg_value_5d_num"].fillna(0) >= config.day_etf_min_avg_value_5d)
        ]
    else:
        pool = pool[~pool["_is_etf"]]

    if pool.empty:
        return []

    stock_has_mcap = (
        (~pool["_is_etf"])
        & pool["_mcap_num"].fillna(0).gt(0)
    ).any()
    pool = pool[
        pool["_is_etf"]
        | (
            (pool["_avg_value_5d_num"].fillna(0) >= float(config.day_stock_min_avg_value_5d))
            & (
                (pool["_mcap_num"].fillna(0) >= float(config.day_stock_min_mcap))
                if stock_has_mcap
                else True
            )
        )
    ]
    if pool.empty:
        return []

    pool = pool[
        ~pool.apply(
            lambda row: is_live_status_disqualified(
                {
                    "market_warning_code": row.get("_market_warning_code"),
                    "management_issue_code": row.get("_management_issue_code"),
                }
            ),
            axis=1,
        )
    ]
    if pool.empty:
        return []

    pool["_live_change_pct_num"] = pool.apply(lambda r: _resolve_change_pct(r, quotes), axis=1)
    pool["_day_intraday_score"] = pool["code"].map(
        lambda code: _day_intraday_structure_score(quotes.get(str(code), {}))
    )
    pool = pool[
        pool["_live_change_pct_num"].isna()
        | (pool["_live_change_pct_num"] > float(config.day_hard_drop_exclude_pct))
    ]
    if pool.empty:
        return []

    pool = pool[
        pool["_retrace_from_high_10d_pct"].isna()
        | (pool["_retrace_from_high_10d_pct"] >= float(config.day_recent_high_retrace_10d_min_pct))
    ]
    if pool.empty:
        return []

    pool["_day_max_change_pct"] = pool.apply(
        lambda row: _resolve_day_max_change_pct(row, config),
        axis=1,
    )
    pool = pool[
        pool["_live_change_pct_num"].isna()
        | (
            (pool["_live_change_pct_num"] >= float(config.day_min_change_pct))
            & (pool["_live_change_pct_num"] <= pool["_day_max_change_pct"])
        )
    ]
    if pool.empty:
        return []

    if news_signal is None:
        pool["score"] = pool.apply(lambda r: _score_day_row(r, quotes, config), axis=1)
    else:
        pool["score"] = pool.apply(lambda r: _score_day_row(r, quotes, config, news_signal), axis=1)
    # 단타는 실시간 강도가 우선이므로 장중 구조 점수를 상승률/거래대금보다 먼저 반영한다.
    pool = pool.sort_values(
        by=["score", "_day_intraday_score", "_live_change_pct_num", "_avg_value_5d_num"],
        ascending=[False, False, False, False]
    )
    if pool.empty:
        return []

    stock_pool = pool[~pool["_is_etf"]]
    etf_pool = pool[pool["_is_etf"]]

    preferred_code: str | None = None
    if not stock_pool.empty and not etf_pool.empty:
        best_stock = stock_pool.iloc[0]
        best_etf = etf_pool.iloc[0]
        if best_stock["score"] >= best_etf["score"] * config.day_stock_prefer_threshold:
            preferred_code = str(best_stock["code"])
        else:
            preferred_code = str(best_etf["code"])
    elif not pool.empty:
        preferred_code = str(pool.iloc[0]["code"])

    sector_keywords = _candidate_sector_keywords(config, news_signal)
    ordered_pool = _diversify_candidate_rows_by_sector(
        pool,
        sector_keywords=sector_keywords,
        news_signal=news_signal,
        preferred_code=preferred_code,
    )

    # Keep the original score order for fallback attempts; only bias the first pick.
    ordered_codes: list[str] = []
    if preferred_code:
        ordered_codes.append(str(preferred_code))
    ordered_codes.extend(
        str(code) for code in ordered_pool["code"].tolist() if str(code) != str(preferred_code)
    )

    deduped_codes: list[str] = []
    seen: set[str] = set()
    for code in ordered_codes:
        if code in seen:
            continue
        seen.add(code)
        deduped_codes.append(code)

    return deduped_codes


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


def _build_quote_codes(merged: pd.DataFrame, limit: int) -> list[str]:
    if merged.empty:
        return []
    top = merged.head(max(1, int(limit)))
    return [str(c) for c in top["code"].tolist()]


def _candidate_sector_keywords(
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None,
) -> dict[str, tuple[str, ...]]:
    if news_signal is not None and news_signal.sector_keywords:
        return news_signal.sector_keywords
    return _load_sector_keywords(config.news_sector_queries_path)


def _diversify_candidate_rows_by_sector(
    df: pd.DataFrame,
    *,
    sector_keywords: dict[str, tuple[str, ...]] | None,
    news_signal: NewsSentimentSignal | None = None,
    preferred_code: str | None = None,
) -> pd.DataFrame:
    if df.empty or "code" not in df.columns or not sector_keywords:
        return df

    working = df.copy()
    working["_primary_sector"] = working.apply(
        lambda row: _resolve_candidate_primary_sector(
            row,
            sector_keywords=sector_keywords,
            news_signal=news_signal,
        ),
        axis=1,
    )
    classified_sectors = {str(sector).strip() for sector in working["_primary_sector"].tolist() if str(sector).strip()}
    if len(classified_sectors) <= 1:
        return working.drop(columns=["_primary_sector"], errors="ignore")

    ordered_indices: list[Hashable] = []
    seen_codes: set[str] = set()
    seen_sectors: set[str] = set()

    def _append_row(idx: Hashable) -> None:
        row = working.loc[idx]
        code = str(row.get("code") or "")
        if not code or code in seen_codes:
            return
        ordered_indices.append(idx)
        seen_codes.add(code)
        sector = str(row.get("_primary_sector") or "").strip()
        if sector:
            seen_sectors.add(sector)

    if preferred_code:
        preferred_mask = working["code"].astype(str) == str(preferred_code)
        if preferred_mask.any():
            _append_row(working.index[preferred_mask][0])

    for idx, row in working.iterrows():
        code = str(row.get("code") or "")
        if not code or code in seen_codes:
            continue
        sector = str(row.get("_primary_sector") or "").strip()
        if sector and sector in seen_sectors:
            continue
        _append_row(idx)

    for idx, row in working.iterrows():
        code = str(row.get("code") or "")
        if not code or code in seen_codes:
            continue
        _append_row(idx)

    if not ordered_indices:
        return working.drop(columns=["_primary_sector"], errors="ignore")
    return working.loc[ordered_indices].drop(columns=["_primary_sector"], errors="ignore").reset_index(drop=True)


def _resolve_candidate_primary_sector(
    row: pd.Series,
    *,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: NewsSentimentSignal | None = None,
) -> str:
    industry_bucket = _clean_text(row.get("industry_bucket_name"))
    if industry_bucket:
        return industry_bucket

    explicit_sector = _clean_text(row.get("theme_sector"))
    if explicit_sector:
        return explicit_sector

    matched = _match_name_to_sectors(str(row.get("name") or ""), sector_keywords)
    if not matched:
        return ""

    if news_signal is None:
        return sorted(matched)[0]

    ranked_matches = sorted(
        matched,
        key=lambda sector: (float(news_signal.sector_scores.get(sector, 0.0)), str(sector)),
        reverse=True,
    )
    return str(ranked_matches[0]) if ranked_matches else ""

def _pick_theme_day_swing_etf(
    *,
    stock_scored: pd.DataFrame,
    etf_candidates: pd.DataFrame,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None,
) -> str | None:
    if (
        news_signal is None
        or etf_candidates is None
        or etf_candidates.empty
        or not bool(config.swing_prefer_sector_etf_on_theme_day)
    ):
        return None

    best_stock = stock_scored.iloc[0]
    matched_sectors = _match_name_to_sectors(
        str(best_stock.get("name") or ""),
        news_signal.sector_keywords,
    )
    if not matched_sectors:
        return None

    etf_pool = etf_candidates.copy()
    etf_pool = etf_pool[~etf_pool.apply(lambda r: is_broad_market_etf(r.to_dict()), axis=1)]
    if etf_pool.empty:
        return None
    etf_pool["source_model"] = False
    etf_pool["_change_pct_num"] = etf_pool.apply(lambda r: _resolve_change_pct(r, quotes), axis=1)
    etf_pool = etf_pool[
        etf_pool["_change_pct_num"].isna()
        | (etf_pool["_change_pct_num"] > float(config.swing_hard_drop_exclude_pct))
    ]
    if etf_pool.empty:
        return None

    etf_pool["score"] = etf_pool.apply(
        lambda r: _score_swing_row(r, quotes, config, news_signal),
        axis=1,
    )

    sector_order = sorted(
        matched_sectors,
        key=lambda sector: float(news_signal.sector_scores.get(sector, 0.0)),
        reverse=True,
    )
    for sector in sector_order:
        sector_score = float(news_signal.sector_scores.get(sector, 0.0))
        if sector_score < float(config.swing_sector_etf_min_sector_score):
            continue

        breadth = int(
            stock_scored["name"]
            .fillna("")
            .map(lambda name: sector in _match_name_to_sectors(str(name), news_signal.sector_keywords))
            .sum()
        )
        if breadth < int(config.swing_sector_etf_min_breadth):
            continue

        themed_etfs = etf_pool[
            etf_pool["name"]
            .fillna("")
            .map(lambda name: sector in _match_name_to_sectors(str(name), news_signal.sector_keywords))
        ].copy()
        if themed_etfs.empty:
            continue

        theme_bonus = (sector_score * 20.0) + min(10.0, max(0, breadth - 1) * 4.0)
        themed_etfs["theme_score"] = themed_etfs["score"] + theme_bonus
        themed_etfs["_preferred_name_rank"] = themed_etfs["name"].fillna("").map(
            lambda name: _theme_etf_name_preference_rank(str(name), sector)
        )
        themed_etfs = themed_etfs[
            themed_etfs["theme_score"] >= float(config.swing_sector_etf_min_score)
        ]
        themed_etfs = themed_etfs[
            themed_etfs["_change_pct_num"].isna()
            | (themed_etfs["_change_pct_num"] >= float(config.swing_sector_etf_min_change_pct))
        ]
        if themed_etfs.empty:
            continue

        themed_etfs = themed_etfs.sort_values(
            by=["_preferred_name_rank", "theme_score", "score", "_change_pct_num", "avg_value_20d"],
            ascending=[True, False, False, False, False],
        )
        return str(themed_etfs.iloc[0]["code"])

    return None


def _match_name_to_sectors(
    name: str,
    sector_keywords: dict[str, tuple[str, ...]],
) -> set[str]:
    return match_name_to_sectors(name, sector_keywords)


def _theme_etf_name_preference_rank(name: str, sector: str) -> int:
    normalized = str(name or "").strip().lower()
    preferred_keywords = _PREFERRED_THEME_ETF_NAME_KEYWORDS.get(str(sector), ())
    for idx, keyword in enumerate(preferred_keywords):
        if keyword in normalized:
            return idx
    return len(preferred_keywords) + 1


def _resolve_market_warning_code(row: pd.Series, quotes: QuoteMap) -> object:
    code = str(row.get("code"))
    q = quotes.get(code, {})
    return q.get("market_warning_code") or row.get("market_warning_code") or row.get("mrkt_warn_cls_code")


def _resolve_management_issue_code(row: pd.Series, quotes: QuoteMap) -> object:
    code = str(row.get("code"))
    q = quotes.get(code, {})
    return (
        q.get("management_issue_code")
        or row.get("management_issue_code")
        or row.get("mang_issu_cls_code")
        or row.get("mang_issu_yn")
        or row.get("admn_item_yn")
    )


def _proxy_codes(config: TradeEngineConfig) -> set[str]:
    codes = {str(config.market_proxy_code).strip(), str(config.kosdaq_proxy_code).strip()}
    return {c for c in codes if c}


def _drop_excluded_codes(df: pd.DataFrame, excluded_codes: set[str]) -> pd.DataFrame:
    if df.empty or "code" not in df.columns or not excluded_codes:
        return df
    out = df.loc[~df["code"].astype(str).isin(excluded_codes)].copy()
    return out.reset_index(drop=True)


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


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()
