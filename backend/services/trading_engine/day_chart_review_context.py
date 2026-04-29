from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pandas as pd

from .candidate_scoring import _day_intraday_structure_score, _resolve_change_pct
from .chart_review_renderer import render_candidate_chart_png
from .intraday import sort_intraday_bars
from .types import Quote, QuoteMap
from .utils import parse_numeric
from .day_chart_review_types import ReviewAsset

if TYPE_CHECKING:
    from .interfaces import TradingAPI
    from .strategy import Candidates

logger = logging.getLogger(__name__)


def build_shortlist(ranked_codes: list[str], *, max_count: int) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for code in ranked_codes:
        code_str = str(code or "").strip()
        if not code_str or code_str in seen:
            continue
        seen.add(code_str)
        ordered.append(code_str)
        if len(ordered) >= max_count:
            break
    return ordered


def build_day_shortlist(
    *,
    ranked_codes: list[str],
    quotes: QuoteMap,
    config,
) -> list[str]:
    base_count = max(1, int(config.day_chart_review_top_n))
    shortlist = build_shortlist(ranked_codes, max_count=base_count)

    wildcard_slots = max(0, int(getattr(config, "day_chart_review_chart_wildcard_slots", 0)))
    if wildcard_slots <= 0:
        return shortlist

    shortlisted_codes = set(shortlist)
    remaining_seen: set[str] = set()
    chart_scored_remaining: list[tuple[float, int, str]] = []
    for rank_index, code in enumerate(ranked_codes):
        code_str = str(code or "").strip()
        if not code_str or code_str in shortlisted_codes or code_str in remaining_seen:
            continue
        remaining_seen.add(code_str)
        quote = quotes.get(code_str, {})
        chart_score = float(_day_intraday_structure_score(quote))
        chart_scored_remaining.append((chart_score, rank_index, code_str))

    if not chart_scored_remaining:
        return shortlist

    chart_scored_remaining.sort(key=lambda item: (-item[0], item[1], item[2]))
    extended = list(shortlist)
    for _, _, code_str in chart_scored_remaining[:wildcard_slots]:
        if code_str in shortlisted_codes:
            continue
        extended.append(code_str)
        shortlisted_codes.add(code_str)
    return extended


def build_day_review_assets(
    *,
    api: "TradingAPI",
    trade_date: str,
    ranked_codes: list[str],
    candidates: "Candidates",
    quotes: QuoteMap,
    config,
    output_dir: str,
) -> list[ReviewAsset]:
    shortlist = build_day_shortlist(
        ranked_codes=ranked_codes,
        quotes=quotes,
        config=config,
    )
    if not shortlist:
        return []

    chart_dir = os.path.join(output_dir, "day_chart_review")
    os.makedirs(chart_dir, exist_ok=True)

    assets: list[ReviewAsset] = []
    for rank, code in enumerate(shortlist, start=1):
        row = find_candidate_row(candidates, code)
        daily_bars = safe_daily_bars(api, code=code, trade_date=trade_date, lookback=80)
        intraday_bars = safe_intraday_bars(api, code=code, trade_date=trade_date, lookback=80)
        if (daily_bars is None or daily_bars.empty) and (intraday_bars is None or intraday_bars.empty):
            continue

        chart_path = os.path.join(chart_dir, f"{trade_date}_{rank}_{code}.png")
        render_candidate_chart_png(
            path=chart_path,
            code=code,
            daily_bars=daily_bars,
            intraday_bars=intraday_bars,
        )
        quote = quotes.get(str(code), {})
        assets.append(
            ReviewAsset(
                code=code,
                meta_text=candidate_meta_text(rank=rank, code=code, row=row, quote=quote),
                chart_path=chart_path,
            )
        )
    return assets


def build_swing_review_assets(
    *,
    api: "TradingAPI",
    trade_date: str,
    ranked_codes: list[str],
    candidates: "Candidates",
    quotes: QuoteMap,
    config,
    output_dir: str,
) -> list[ReviewAsset]:
    shortlist = build_shortlist(ranked_codes, max_count=max(1, int(config.swing_chart_review_top_n)))
    if not shortlist:
        return []

    chart_dir = os.path.join(output_dir, "swing_chart_review")
    os.makedirs(chart_dir, exist_ok=True)

    assets: list[ReviewAsset] = []
    for rank, code in enumerate(shortlist, start=1):
        row = find_candidate_row(candidates, code)
        daily_bars = safe_daily_bars(api, code=code, trade_date=trade_date, lookback=90)
        if daily_bars is None or daily_bars.empty:
            continue

        recent_zoom = daily_bars.tail(24).copy()
        chart_path = os.path.join(chart_dir, f"{trade_date}_{rank}_{code}.png")
        render_candidate_chart_png(
            path=chart_path,
            code=code,
            daily_bars=daily_bars,
            intraday_bars=recent_zoom,
        )
        quote = quotes.get(str(code), {})
        assets.append(
            ReviewAsset(
                code=code,
                meta_text=candidate_meta_text(rank=rank, code=code, row=row, quote=quote),
                chart_path=chart_path,
            )
        )
    return assets


def find_candidate_row(candidates: "Candidates", code: str) -> pd.Series | None:
    for attr_name in ("popular", "model", "etf", "merged"):
        frame = getattr(candidates, attr_name, None)
        if frame is None or getattr(frame, "empty", True) or "code" not in frame.columns:
            continue
        rows = frame[frame["code"].astype(str) == str(code)]
        if rows.empty:
            continue
        return rows.iloc[0]
    return None


def safe_daily_bars(api: "TradingAPI", *, code: str, trade_date: str, lookback: int) -> pd.DataFrame:
    try:
        bars = api.daily_bars(code=code, end=trade_date, lookback=lookback)
    except Exception:
        logger.debug("day chart review daily_bars failed code=%s", code, exc_info=True)
        return pd.DataFrame()
    return bars.copy() if isinstance(bars, pd.DataFrame) else pd.DataFrame()


def safe_intraday_bars(api: "TradingAPI", *, code: str, trade_date: str, lookback: int) -> pd.DataFrame:
    intraday_fn = getattr(api, "intraday_bars", None)
    if not callable(intraday_fn):
        return pd.DataFrame()
    try:
        bars = intraday_fn(code=code, asof=trade_date, lookback=lookback)
    except Exception:
        logger.debug("day chart review intraday_bars failed code=%s", code, exc_info=True)
        return pd.DataFrame()
    if not isinstance(bars, pd.DataFrame):
        return pd.DataFrame()
    return sort_intraday_bars(bars)


def candidate_meta_text(
    *,
    rank: int,
    code: str,
    row: pd.Series | None,
    quote: Quote,
) -> str:
    name = str(row.get("name") if row is not None else quote.get("name") or "").strip() or code
    avg_value_label, avg_value = resolve_candidate_avg_value(row)
    change_pct = _resolve_change_pct(row, {str(code): quote}) if row is not None else None
    if change_pct is None:
        change_pct = parse_numeric(quote.get("change_pct")) or parse_numeric(quote.get("change_rate"))
    breakout_vs_prev_high = parse_numeric(row.get("breakout_vs_prev_high_10d_pct")) if row is not None else None
    close = parse_numeric(quote.get("price"))
    if close is None and row is not None:
        close = parse_numeric(row.get("close"))
    return (
        f"후보 {rank}: {name}({code})\n"
        f"- 현재가: {close if close is not None else 'N/A'}\n"
        f"- 등락률: {change_pct if change_pct is not None else 'N/A'}%\n"
        f"- {avg_value_label}: "
        f"{round(avg_value / 1e8, 1) if avg_value is not None else 'N/A'}억\n"
        f"- 직전 10일 최고 종가 대비: {breakout_vs_prev_high if breakout_vs_prev_high is not None else 'N/A'}%"
    )


def resolve_candidate_avg_value(row: pd.Series | None) -> tuple[str, float | None]:
    if row is None:
        return "평균 거래대금", None
    avg_value_5d = parse_numeric(row.get("avg_value_5d"))
    if avg_value_5d is not None:
        return "5일 평균 거래대금", avg_value_5d
    avg_value_20d = parse_numeric(row.get("avg_value_20d"))
    if avg_value_20d is not None:
        return "20일 평균 거래대금", avg_value_20d
    return "평균 거래대금", None


__all__ = [
    "build_day_review_assets",
    "build_day_shortlist",
    "build_shortlist",
    "build_swing_review_assets",
    "candidate_meta_text",
    "find_candidate_row",
    "resolve_candidate_avg_value",
    "safe_daily_bars",
    "safe_intraday_bars",
]
