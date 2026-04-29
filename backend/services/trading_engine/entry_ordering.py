from __future__ import annotations

from typing import TYPE_CHECKING

from .news_sentiment import _load_sector_keywords
from .utils import match_name_to_sectors, parse_numeric

if TYPE_CHECKING:
    from .news_sentiment import NewsSentimentSignal
    from .strategy import Candidates
    from .types import Quote


def krx_tick_size(price: float) -> int:
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def resolve_day_entry_order(
    *,
    quote: Quote | None,
    configured_order_type: str,
) -> tuple[str, int | None]:
    normalized = str(configured_order_type or "").strip().lower()
    if normalized != "best":
        return configured_order_type, None

    price_now = parse_numeric((quote or {}).get("price"))
    if price_now is None or price_now <= 0:
        return "limit", None

    tick = krx_tick_size(float(price_now))
    return "limit", int(price_now) + tick


def swing_retry_codes_with_sector_peers(
    *,
    ranked_codes: list[str],
    candidates: "Candidates",
    config,
    news_signal: "NewsSentimentSignal | None" = None,
) -> list[str]:
    if len(ranked_codes) < 2:
        return ranked_codes

    sector_keywords = (
        news_signal.sector_keywords
        if news_signal is not None and getattr(news_signal, "sector_keywords", None)
        else _load_sector_keywords(config.news_sector_queries_path)
    )
    candidate_frame = build_swing_retry_candidate_frame(candidates)
    if candidate_frame.empty:
        return ranked_codes

    anchor_code = str(ranked_codes[0]).strip()
    second_code = str(ranked_codes[1]).strip()
    anchor_sector = resolve_swing_candidate_sector(
        code=anchor_code,
        candidate_frame=candidate_frame,
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )
    if not anchor_sector:
        return ranked_codes

    peer_codes: list[str] = []
    for _, row in candidate_frame.iterrows():
        code = str(row.get("code") or "").strip()
        if not code or code == anchor_code:
            continue
        if resolve_swing_row_sector(
            row=row,
            sector_keywords=sector_keywords,
            news_signal=news_signal,
        ) != anchor_sector:
            continue
        peer_codes.append(code)
        if len(peer_codes) >= 3:
            break

    ordered: list[str] = []
    seen: set[str] = set()
    for code in [anchor_code, second_code, *peer_codes, *ranked_codes[2:]]:
        normalized = str(code or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def build_swing_retry_candidate_frame(candidates: "Candidates"):
    import pandas as pd

    frames = [
        getattr(candidates, "model", pd.DataFrame()),
        getattr(candidates, "merged", pd.DataFrame()),
        getattr(candidates, "popular", pd.DataFrame()),
        getattr(candidates, "etf", pd.DataFrame()),
    ]
    usable = [frame for frame in frames if frame is not None and not frame.empty and "code" in frame.columns]
    if not usable:
        return pd.DataFrame()

    merged = pd.concat(usable, ignore_index=True, sort=False)
    sort_cols = [col for col in ("score", "avg_value_20d", "avg_value_5d", "change_pct") if col in merged.columns]
    if sort_cols:
        ascending = [False] * len(sort_cols)
        merged = merged.sort_values(by=sort_cols, ascending=ascending, na_position="last")
    return merged.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)


def resolve_swing_candidate_sector(
    *,
    code: str,
    candidate_frame,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: "NewsSentimentSignal | None" = None,
) -> str:
    matches = candidate_frame[candidate_frame["code"].astype(str) == str(code)]
    if matches.empty:
        return ""
    return resolve_swing_row_sector(
        row=matches.iloc[0],
        sector_keywords=sector_keywords,
        news_signal=news_signal,
    )


def resolve_swing_row_sector(
    *,
    row,
    sector_keywords: dict[str, tuple[str, ...]],
    news_signal: "NewsSentimentSignal | None" = None,
) -> str:
    for key in (
        "industry_bucket_name",
        "theme_sector",
        "industry_small_name",
        "industry_medium_name",
        "industry_large_name",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value

    matched = match_name_to_sectors(str(row.get("name") or ""), sector_keywords)
    if not matched:
        return ""
    if news_signal is None:
        return sorted(matched)[0]
    return max(
        matched,
        key=lambda sector: (float(news_signal.sector_scores.get(sector, 0.0)), str(sector)),
    )


__all__ = [
    "build_swing_retry_candidate_frame",
    "krx_tick_size",
    "resolve_day_entry_order",
    "resolve_swing_candidate_sector",
    "resolve_swing_row_sector",
    "swing_retry_codes_with_sector_peers",
]
