from __future__ import annotations

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
from .news_sentiment import NewsSentimentSignal
from .screeners import etf_swing_screener, model_screener, popular_screener
from .strategy_ranking import (
    _attach_popular_liquidity_signals,
    _merge_candidates,
    _resolve_candidate_price,
    _resolve_day_entry_budget_cash,
    _resolve_day_max_change_pct,
)
from .strategy_theme import (
    _candidate_sector_keywords,
    _diversify_candidate_rows_by_sector,
    _match_name_to_sectors,
    _pick_theme_day_swing_etf,
    _resolve_candidate_primary_sector,
    _theme_etf_name_preference_rank,
)
from .types import QuoteMap
from .utils import is_broad_market_etf, is_live_status_disqualified, parse_numeric


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
            resolve_change_pct_fn=_resolve_change_pct,
            score_swing_row_fn=_score_swing_row,
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
    pool = pool.sort_values(
        by=["score", "_day_intraday_score", "_live_change_pct_num", "_avg_value_5d_num"],
        ascending=[False, False, False, False],
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


def _build_quote_codes(merged: pd.DataFrame, limit: int) -> list[str]:
    if merged.empty:
        return []
    top = merged.head(max(1, int(limit)))
    return [str(c) for c in top["code"].tolist()]


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
