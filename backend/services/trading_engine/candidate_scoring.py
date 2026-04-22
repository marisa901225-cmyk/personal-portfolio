from __future__ import annotations

from typing import Any

import pandas as pd

from .config import TradeEngineConfig
from .news_sentiment import NewsSentimentSignal
from .utils import parse_numeric


def _score_swing_row(
    row: pd.Series,
    quotes: dict[str, dict[str, Any]],
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> float:
    code = str(row.get("code"))
    q = quotes.get(code, {})
    close = parse_numeric(q.get("price")) or parse_numeric(row.get("close")) or 0.0
    ma20 = parse_numeric(row.get("ma20"))
    ma60 = parse_numeric(row.get("ma60"))
    avg20 = parse_numeric(row.get("avg_value_20d")) or 0.0

    score = 0.0
    trend_tier = str(row.get("trend_tier") or "").strip().lower()
    if bool(row.get("source_model", False)):
        score += 30.0 if trend_tier == "strict" else 22.0

    if ma20 and close > ma20:
        score += 10.0
    if ma20 and ma60 and ma20 > ma60:
        score += 10.0

    score += min(20.0, max(0.0, avg20 / 100_000_000_000))

    if ma20 and ma20 > 0 and (close / ma20 - 1.0) > 0.08:
        score -= 20.0

    chg = _resolve_change_pct(row, quotes)
    if chg is not None:
        cap_pct = max(float(config.swing_momentum_bonus_cap_pct), 1e-9)
        if chg >= 0:
            score += min(
                float(config.swing_momentum_bonus_max),
                float(config.swing_momentum_bonus_max) * (chg / cap_pct),
            )
        else:
            penalty_cap = max(abs(float(config.swing_hard_drop_exclude_pct)), cap_pct, 1.0)
            penalty_ratio = min(1.0, abs(chg) / penalty_cap)
            score -= float(config.swing_negative_penalty_max) * penalty_ratio

    score += _swing_quote_structure_score(q)
    score += _swing_industry_trend_score(row, config)
    score += _news_score_bonus(
        row,
        news_signal,
        weight=config.news_swing_weight,
        market_fallback_ratio=config.news_market_fallback_ratio,
    )
    return score


def _swing_industry_trend_score(
    row: pd.Series,
    config: TradeEngineConfig,
) -> float:
    close = parse_numeric(row.get("industry_close"))
    ma5 = parse_numeric(row.get("industry_ma5"))
    ma20 = parse_numeric(row.get("industry_ma20"))
    day_change_pct = parse_numeric(row.get("industry_day_change_pct"))
    change_5d_pct = parse_numeric(row.get("industry_5d_change_pct"))

    if close is None and ma5 is None and ma20 is None and day_change_pct is None and change_5d_pct is None:
        return 0.0

    bonus_cap = max(0.0, float(config.swing_industry_trend_bonus_max))
    penalty_cap = max(0.0, float(config.swing_industry_negative_penalty_max))
    score = 0.0
    trend_block = bonus_cap * 0.4

    if close is not None and ma20 is not None and ma20 > 0:
        score += trend_block if close > ma20 else -min(penalty_cap * 0.45, trend_block)

    if ma5 is not None and ma20 is not None and ma20 > 0:
        score += trend_block if ma5 > ma20 else -min(penalty_cap * 0.35, trend_block)

    if day_change_pct is not None:
        if day_change_pct >= 0:
            score += min(bonus_cap * 0.15, float(day_change_pct) * 0.9)
        else:
            score -= min(penalty_cap * 0.35, abs(float(day_change_pct)) * 1.0)

    if change_5d_pct is not None:
        if change_5d_pct >= 0:
            score += min(bonus_cap * 0.3, float(change_5d_pct) * 0.45)
        else:
            score -= min(penalty_cap * 0.5, abs(float(change_5d_pct)) * 0.55)

    return score


def _swing_quote_structure_score(quote: dict[str, Any]) -> float:
    price = parse_numeric(quote.get("price"))
    open_price = parse_numeric(quote.get("open"))
    high_price = parse_numeric(quote.get("high"))
    low_price = parse_numeric(quote.get("low"))

    if price is None or price <= 0:
        return 0.0

    score = 0.0

    if open_price is not None and open_price > 0:
        open_change_pct = (price / open_price - 1.0) * 100.0
        if open_change_pct >= 0:
            score += min(4.0, open_change_pct * 0.9)
        else:
            score -= min(4.0, abs(open_change_pct) * 1.1)

    if high_price is not None and high_price > 0 and price <= high_price:
        retrace_from_high_pct = (price / high_price - 1.0) * 100.0
        if retrace_from_high_pct >= -1.5:
            score += 4.0 * (1.0 - abs(retrace_from_high_pct) / 1.5)
        else:
            penalty_ratio = min(1.0, (abs(retrace_from_high_pct) - 1.5) / 3.5)
            score -= 6.0 * penalty_ratio

    if (
        high_price is not None
        and low_price is not None
        and high_price > low_price
        and low_price > 0
    ):
        location_ratio = (price - low_price) / (high_price - low_price)
        location_ratio = min(1.0, max(0.0, location_ratio))
        score += (location_ratio - 0.5) * 4.0

    return score


def _score_day_row(
    row: pd.Series,
    quotes: dict[str, dict[str, Any]],
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> float:
    code = str(row.get("code"))
    q = quotes.get(code, {})

    score = 30.0
    avg5 = parse_numeric(row.get("_avg_value_5d_num"))
    if avg5 is None:
        avg5 = parse_numeric(row.get("avg_value_5d")) or 0.0
    score += min(20.0, avg5 / 100_000_000_000)

    value_rank = parse_numeric(row.get("value_rank"))
    if value_rank is not None and value_rank > 0:
        # Reward names that are already ranking near the top of today's traded-value list.
        score += max(0.0, 14.0 - ((min(float(value_rank), 200.0) - 1.0) * 0.07))

    volume_rank = parse_numeric(row.get("volume_rank"))
    if volume_rank is not None and volume_rank > 0:
        score += max(0.0, 4.0 - ((min(float(volume_rank), 120.0) - 1.0) * 0.03))

    hts_view_rank = parse_numeric(row.get("hts_view_rank"))
    if hts_view_rank is not None and hts_view_rank > 0:
        hts_top_n = max(1.0, float(getattr(config, "day_hts_top_view_top_n", 20)))
        hts_bonus_max = max(0.0, float(getattr(config, "day_hts_top_view_bonus_max", 0.0)))
        rank_ratio = (min(float(hts_view_rank), hts_top_n) - 1.0) / max(1.0, hts_top_n - 1.0)
        score += max(0.0, hts_bonus_max * (1.0 - rank_ratio))

    chg = _resolve_change_pct(row, quotes)
    if chg is not None:
        cap_pct = max(config.day_momentum_bonus_cap_pct, 1e-9)
        if 0.5 <= chg <= cap_pct:
            score += config.day_momentum_bonus_max * (chg / cap_pct)
        elif chg > 20.0:
            score -= 10.0
        elif chg < 0:
            score -= min(
                float(config.day_negative_penalty_max),
                abs(float(chg)) * float(config.day_negative_penalty_per_pct),
            )

    bid = parse_numeric(q.get("bid"))
    ask = parse_numeric(q.get("ask"))
    price = parse_numeric(q.get("price"))
    if bid and ask and price and price > 0:
        spread_pct = (ask - bid) / price
        if spread_pct > 0.015:
            score -= 5.0

    if bool(row.get("fallback_selected", False)):
        score -= 5.0
    if bool(row.get("legacy_top10_selected", False)):
        score += 2.0
    if not _as_bool(row.get("_is_etf", row.get("is_etf", False))):
        score += 5.0

    intraday_strength_score = _day_intraday_structure_score(q)
    score += intraday_strength_score * float(getattr(config, "day_intraday_strength_weight", 1.0))
    score += _day_industry_trend_score(row, config)
    score += _news_score_bonus(
        row,
        news_signal,
        weight=config.news_day_weight,
        market_fallback_ratio=config.news_market_fallback_ratio,
    )
    return score


def _day_industry_trend_score(
    row: pd.Series,
    config: TradeEngineConfig,
) -> float:
    close = parse_numeric(row.get("industry_close"))
    ma5 = parse_numeric(row.get("industry_ma5"))
    ma20 = parse_numeric(row.get("industry_ma20"))
    day_change_pct = parse_numeric(row.get("industry_day_change_pct"))
    change_5d_pct = parse_numeric(row.get("industry_5d_change_pct"))

    if close is None and ma5 is None and ma20 is None and day_change_pct is None and change_5d_pct is None:
        return 0.0

    bonus_cap = max(0.0, float(config.day_industry_trend_bonus_max))
    penalty_cap = max(0.0, float(config.day_industry_negative_penalty_max))
    score = 0.0
    trend_block = bonus_cap * 0.35

    if close is not None and ma20 is not None and ma20 > 0:
        score += trend_block if close > ma20 else -min(penalty_cap * 0.35, trend_block)

    if ma5 is not None and ma20 is not None and ma20 > 0:
        score += trend_block if ma5 > ma20 else -min(penalty_cap * 0.35, trend_block)

    if day_change_pct is not None:
        if day_change_pct >= 0:
            score += min(bonus_cap * 0.2, float(day_change_pct) * 1.2)
        else:
            score -= min(penalty_cap * 0.5, abs(float(day_change_pct)) * 1.5)

    if change_5d_pct is not None:
        if change_5d_pct >= 0:
            score += min(bonus_cap * 0.1, float(change_5d_pct) * 0.35)
        else:
            score -= min(penalty_cap * 0.3, abs(float(change_5d_pct)) * 0.45)

    return score


def _day_intraday_structure_score(quote: dict[str, Any]) -> float:
    price = parse_numeric(quote.get("price"))
    open_price = parse_numeric(quote.get("open"))
    high_price = parse_numeric(quote.get("high"))
    low_price = parse_numeric(quote.get("low"))

    if price is None or price <= 0:
        return 0.0

    score = 0.0

    if open_price is not None and open_price > 0:
        open_change_pct = (price / open_price - 1.0) * 100.0
        if open_change_pct >= 0:
            score += min(6.0, open_change_pct * 1.2)
        else:
            score -= min(6.0, abs(open_change_pct) * 1.5)

    if high_price is not None and high_price > 0 and price <= high_price:
        retrace_from_high_pct = (price / high_price - 1.0) * 100.0
        if retrace_from_high_pct >= -1.0:
            score += 6.0 * (1.0 - abs(retrace_from_high_pct))
        else:
            penalty_ratio = min(1.0, (abs(retrace_from_high_pct) - 1.0) / 3.0)
            score -= 8.0 * penalty_ratio

    if (
        high_price is not None
        and low_price is not None
        and high_price > low_price
        and low_price > 0
    ):
        location_ratio = (price - low_price) / (high_price - low_price)
        location_ratio = min(1.0, max(0.0, location_ratio))
        score += (location_ratio - 0.5) * 6.0

        intraday_range_pct = ((high_price / low_price) - 1.0) * 100.0
        if intraday_range_pct > 0:
            score += min(4.0, intraday_range_pct * location_ratio * 0.6)

    return score


def _news_score_bonus(
    row: pd.Series,
    news_signal: NewsSentimentSignal | None,
    *,
    weight: float,
    market_fallback_ratio: float,
) -> float:
    if news_signal is None or abs(weight) < 1e-9:
        return 0.0

    sentiment, matched = news_signal.score_for_name(str(row.get("name", "")))
    if not matched:
        weight = weight * max(0.0, float(market_fallback_ratio))
    return float(sentiment) * float(weight)


def _resolve_change_pct(row: pd.Series, quotes: dict[str, dict[str, Any]]) -> float | None:
    code = str(row.get("code"))
    q = quotes.get(code, {})
    chg = parse_numeric(q.get("change_pct"))
    if chg is None:
        chg = parse_numeric(q.get("change_rate"))
    if chg is None:
        chg = parse_numeric(row.get("_live_change_pct_num"))
    if chg is None:
        chg = parse_numeric(row.get("_change_pct_num"))
    if chg is None:
        chg = parse_numeric(row.get("change_pct"))
    return chg


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"y", "yes", "true", "1", "etf"}
