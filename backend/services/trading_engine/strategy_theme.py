from __future__ import annotations

from collections.abc import Hashable

import pandas as pd

from .config import TradeEngineConfig
from .news_sentiment import NewsSentimentSignal, _load_sector_keywords
from .types import QuoteMap
from .utils import is_broad_market_etf, match_name_to_sectors

_PREFERRED_THEME_ETF_NAME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "semiconductor": ("kodex 반도체",),
}


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


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
    resolve_change_pct_fn,
    score_swing_row_fn,
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
    etf_pool["_change_pct_num"] = etf_pool.apply(lambda r: resolve_change_pct_fn(r, quotes), axis=1)
    etf_pool = etf_pool[
        etf_pool["_change_pct_num"].isna()
        | (etf_pool["_change_pct_num"] > float(config.swing_hard_drop_exclude_pct))
    ]
    if etf_pool.empty:
        return None

    etf_pool["score"] = etf_pool.apply(
        lambda r: score_swing_row_fn(r, quotes, config, news_signal),
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
