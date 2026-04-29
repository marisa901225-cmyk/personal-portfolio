from __future__ import annotations

import pandas as pd

from .config import TradeEngineConfig
from .industry_trend import clean_text, resolve_sector_bucket_name
from .news_sentiment import NewsSentimentSignal, _load_sector_keywords
from .utils import match_name_to_sectors, normalize_code, parse_numeric


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


def _popular_sector_keywords(
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None,
) -> dict[str, tuple[str, ...]]:
    if news_signal is not None and news_signal.sector_keywords:
        return news_signal.sector_keywords
    return _load_sector_keywords(config.news_sector_queries_path)


def _select_sector_bucket_rows(
    liquidity_df: pd.DataFrame,
    *,
    sector_keywords: dict[str, tuple[str, ...]],
    per_sector_top_n: int,
    news_signal: NewsSentimentSignal | None = None,
) -> pd.DataFrame:
    if liquidity_df is None or liquidity_df.empty or per_sector_top_n <= 0:
        return pd.DataFrame()

    working = liquidity_df.copy()
    working["_bucket_key"] = working.apply(
        lambda row: resolve_sector_bucket_name(
            row,
            sector_keywords=sector_keywords,
            news_signal=news_signal,
        ),
        axis=1,
    )
    working = working[working["_bucket_key"].astype(str).str.strip() != ""].copy()
    if working.empty:
        return pd.DataFrame()

    selected_rows: list[dict[str, object]] = []
    seen_codes: set[str] = set()
    for bucket_name, sector_rows in working.groupby("_bucket_key", sort=False):
        if sector_rows.empty:
            continue
        sector_rows = sector_rows.sort_values(
            by=["value_rank", "avg_value_5d", "change_pct", "volume_rank", "name"],
            ascending=[True, False, False, True, True],
            na_position="last",
        )
        taken = 0
        for _, row in sector_rows.iterrows():
            code = str(row.get("code") or "")
            if not code or code in seen_codes:
                continue
            payload = row.to_dict()
            payload["sector_bucket_selected"] = True
            payload["legacy_top10_selected"] = bool(payload.get("legacy_top10_selected", False))
            payload["industry_bucket_name"] = clean_text(payload.get("industry_bucket_name")) or clean_text(bucket_name)
            selected_rows.append(payload)
            seen_codes.add(code)
            taken += 1
            if taken >= int(per_sector_top_n):
                break

    if not selected_rows:
        return pd.DataFrame()
    return pd.DataFrame(selected_rows)


def _select_legacy_popular_rows(
    liquidity_df: pd.DataFrame,
    *,
    volume_df: pd.DataFrame,
    top_n: int,
) -> pd.DataFrame:
    if liquidity_df is None or liquidity_df.empty or top_n <= 0:
        return pd.DataFrame()

    top_a = liquidity_df.sort_values(
        by=["value_rank", "avg_value_5d", "change_pct", "volume_rank", "name"],
        ascending=[True, False, False, True, True],
        na_position="last",
    ).head(top_n).copy()
    top_a["value_rank_5d_top10"] = range(1, len(top_a) + 1)
    top_a["legacy_top10_selected"] = True
    top_a["sector_bucket_selected"] = False

    b_codes = set(volume_df["code"].astype(str)) if volume_df is not None and not volume_df.empty else set()
    inter = top_a[top_a["code"].astype(str).isin(b_codes)].copy()
    if not inter.empty:
        return inter

    fallback = liquidity_df[liquidity_df["code"].astype(str).isin(b_codes)].sort_values(
        by=["value_rank", "avg_value_5d", "change_pct", "volume_rank", "name"],
        ascending=[True, False, False, True, True],
        na_position="last",
    ).head(top_n).copy()
    fallback["value_rank_5d_top10"] = range(1, len(fallback) + 1)
    fallback["fallback_selected"] = True
    fallback["legacy_top10_selected"] = True
    fallback["sector_bucket_selected"] = False
    return fallback


def _combine_popular_rows(
    sector_bucket: pd.DataFrame,
    legacy_top: pd.DataFrame,
) -> pd.DataFrame:
    combined_rows: list[dict[str, object]] = []
    by_code: dict[str, dict[str, object]] = {}

    for block in (sector_bucket, legacy_top):
        if block is None or block.empty:
            continue
        for _, row in block.iterrows():
            payload = row.to_dict()
            code = str(payload.get("code") or "")
            if not code:
                continue
            if code not in by_code:
                by_code[code] = payload
                combined_rows.append(by_code[code])
                continue
            by_code[code]["fallback_selected"] = bool(by_code[code].get("fallback_selected", False)) or bool(
                payload.get("fallback_selected", False)
            )
            by_code[code]["sector_bucket_selected"] = bool(by_code[code].get("sector_bucket_selected", False)) or bool(
                payload.get("sector_bucket_selected", False)
            )
            by_code[code]["legacy_top10_selected"] = bool(by_code[code].get("legacy_top10_selected", False)) or bool(
                payload.get("legacy_top10_selected", False)
            )
            if not by_code[code].get("value_rank_5d_top10") and payload.get("value_rank_5d_top10"):
                by_code[code]["value_rank_5d_top10"] = payload.get("value_rank_5d_top10")

    if not combined_rows:
        return pd.DataFrame()
    out = pd.DataFrame(combined_rows)
    return out.sort_values(
        by=["legacy_top10_selected", "value_rank", "avg_value_5d", "change_pct"],
        ascending=[False, True, False, False],
        na_position="last",
    ).reset_index(drop=True)


def _inject_theme_candidates(
    base: pd.DataFrame,
    liquidity_df: pd.DataFrame,
    news_signal: NewsSentimentSignal | None,
    config: TradeEngineConfig,
) -> pd.DataFrame:
    if (
        news_signal is None
        or base is None
        or liquidity_df is None
        or liquidity_df.empty
        or not bool(config.day_theme_candidate_injection_enabled)
    ):
        return base

    max_injections = max(0, int(config.day_theme_candidate_max_injections))
    if max_injections <= 0:
        return base

    min_sector_score = float(config.day_theme_candidate_min_sector_score)
    strong_sectors = [
        sector
        for sector, score in sorted(
            news_signal.sector_scores.items(),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        if float(score) >= min_sector_score
    ]
    if not strong_sectors:
        return base

    candidates = liquidity_df.copy()
    candidates = candidates[
        candidates["avg_value_5d"].fillna(0) >= float(config.day_theme_candidate_min_avg_value_5d)
    ]
    if candidates.empty:
        return base

    candidates["_matched_sectors"] = candidates["name"].fillna("").map(
        lambda name: match_name_to_sectors(str(name), news_signal.sector_keywords)
    )

    seen_codes = set(base["code"].astype(str)) if not base.empty and "code" in base.columns else set()
    injected_rows: list[dict[str, object]] = []
    for sector in strong_sectors:
        sector_rows = candidates[
            ~candidates["code"].astype(str).isin(seen_codes)
            & candidates["_matched_sectors"].map(lambda matched: sector in matched)
        ].copy()
        if sector_rows.empty:
            continue

        sector_rows = sector_rows.sort_values(
            by=["avg_value_5d", "change_pct", "volume_rank"],
            ascending=[False, False, True],
            na_position="last",
        )
        top_row = sector_rows.iloc[0].to_dict()
        top_row["theme_injected"] = True
        top_row["theme_sector"] = sector
        injected_rows.append(top_row)
        seen_codes.add(str(top_row.get("code", "")))
        if len(injected_rows) >= max_injections:
            break

    if not injected_rows:
        return base

    injected_df = pd.DataFrame(injected_rows)
    return pd.concat([base, injected_df], ignore_index=True, sort=False)
