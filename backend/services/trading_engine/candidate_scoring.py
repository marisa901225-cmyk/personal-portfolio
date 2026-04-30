from __future__ import annotations

import pandas as pd

from .config import TradeEngineConfig
from .global_market_signal import GlobalMarketSignal, global_signal_bonus_for_row
from .news_sentiment import NewsSentimentSignal
from .types import Quote, QuoteMap
from .utils import parse_numeric

_QUOTE_VALUE_KEYS = ("value", "trading_value", "acc_trdval", "volume_value", "거래대금")
_QUOTE_VOLUME_KEYS = ("volume", "acml_vol", "trade_volume", "거래량")


def _score_swing_row(
    row: pd.Series,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
    global_signal: GlobalMarketSignal | None = None,
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
        score += (
            float(getattr(config, "swing_source_model_strict_bonus", 30.0))
            if trend_tier == "strict"
            else float(getattr(config, "swing_source_model_relaxed_bonus", 22.0))
        )

    if ma20 and close > ma20:
        score += float(getattr(config, "swing_ma20_bonus", 10.0))
    if ma20 and ma60 and ma20 > ma60:
        score += float(getattr(config, "swing_ma20_cross_bonus", 10.0))

    score += min(
        float(getattr(config, "swing_avg_value_bonus_max", 20.0)),
        max(0.0, avg20 / max(float(getattr(config, "swing_avg_value_bonus_unit", 100_000_000_000)), 1e-9)),
    )
    if ma20 and ma20 > 0:
        premium_pct = (close / ma20 - 1.0) * 100.0
        score -= _linear_threshold_penalty(
            premium_pct,
            start_pct=float(getattr(config, "swing_ma20_premium_penalty_start_pct", 8.0)),
            full_pct=float(getattr(config, "swing_ma20_premium_penalty_full_pct", 18.0)),
            max_penalty=float(getattr(config, "swing_ma20_premium_penalty_max", 20.0)),
        )

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

    score += _swing_quote_structure_score(row, q, config)
    score -= _quote_volatility_penalty(
        q,
        start_pct=float(getattr(config, "swing_volatility_penalty_start_pct", 6.0)),
        full_pct=float(getattr(config, "swing_volatility_penalty_full_pct", 16.0)),
        max_penalty=float(getattr(config, "swing_volatility_penalty_max", 8.0)),
    )
    score += _swing_popular_liquidity_score(row)
    score += _swing_industry_trend_score(row, config)
    score += _news_score_bonus(
        row,
        news_signal,
        weight=config.news_swing_weight,
        market_fallback_ratio=config.news_market_fallback_ratio,
    )
    score += global_signal_bonus_for_row(
        row,
        global_signal,
        config,
        strategy="S",
        news_signal=news_signal,
    )
    return score


def _swing_popular_liquidity_score(row: pd.Series) -> float:
    score = 0.0

    liquidity_rank = parse_numeric(row.get("popular_liquidity_rank"))
    if liquidity_rank is not None and liquidity_rank > 0:
        score += max(0.0, 10.0 - ((min(float(liquidity_rank), 100.0) - 1.0) * 0.09))

    legacy_rank = parse_numeric(row.get("value_rank_5d_top10"))
    if legacy_rank is not None and legacy_rank > 0:
        score += max(0.0, 5.0 - ((min(float(legacy_rank), 15.0) - 1.0) * 0.3))

    if bool(row.get("legacy_top10_selected", False)):
        score += 2.0

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


def _swing_quote_structure_score(
    row: pd.Series,
    quote: Quote,
    config: TradeEngineConfig,
) -> float:
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
        location_score = (location_ratio - 0.5) * 4.0
        score += location_score * _swing_structure_volume_weight(row, quote, config)

    return score


def _score_day_row(
    row: pd.Series,
    quotes: QuoteMap,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
    global_signal: GlobalMarketSignal | None = None,
) -> float:
    code = str(row.get("code"))
    q = quotes.get(code, {})
    intraday_strength_score = _day_intraday_structure_score(q)
    is_etf = _as_bool(row.get("_is_etf", row.get("is_etf", False)))

    score = float(getattr(config, "day_base_score", 30.0))
    avg5 = parse_numeric(row.get("_avg_value_5d_num"))
    if avg5 is None:
        avg5 = parse_numeric(row.get("avg_value_5d")) or 0.0
    score += min(
        float(getattr(config, "day_avg_value_bonus_max", 20.0)),
        avg5 / max(float(getattr(config, "day_avg_value_bonus_unit", 100_000_000_000)), 1e-9),
    )

    value_rank = parse_numeric(row.get("value_rank"))
    if value_rank is not None and value_rank > 0:
        score += _day_rank_group_bonus(
            float(value_rank),
            top_bonus=14.0,
            mid_bonus=10.5,
            lower_bonus=7.0,
            floor_bonus=3.5,
            top_cutoff=10.0,
            mid_cutoff=30.0,
            lower_cutoff=80.0,
            max_rank=200.0,
        )

    volume_rank = parse_numeric(row.get("volume_rank"))
    if volume_rank is not None and volume_rank > 0:
        score += _day_rank_group_bonus(
            float(volume_rank),
            top_bonus=4.0,
            mid_bonus=3.0,
            lower_bonus=2.0,
            floor_bonus=1.0,
            top_cutoff=10.0,
            mid_cutoff=30.0,
            lower_cutoff=60.0,
            max_rank=120.0,
        )

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
            momentum_bonus = (
                float(config.day_momentum_bonus_max)
                * (chg / cap_pct)
                * _day_momentum_alignment_multiplier(intraday_strength_score)
            )
            if is_etf:
                momentum_bonus *= float(getattr(config, "day_etf_momentum_bonus_scale", 0.60))
            score += (
                momentum_bonus
            )
        elif chg > 20.0:
            score -= float(getattr(config, "day_extreme_momentum_penalty", 10.0))
        elif chg < 0:
            negative_penalty_cap = max(float(config.day_negative_penalty_max), 0.0)
            negative_penalty_full_pct = float(getattr(config, "day_negative_penalty_full_pct", 0.0) or 0.0)
            if negative_penalty_full_pct <= 0:
                negative_penalty_full_pct = negative_penalty_cap / max(
                    float(config.day_negative_penalty_per_pct),
                    1e-9,
                )
            score -= _linear_threshold_penalty(
                abs(float(chg)),
                start_pct=0.0,
                full_pct=max(negative_penalty_full_pct, 1e-9),
                max_penalty=negative_penalty_cap,
            )

    bid = parse_numeric(q.get("bid"))
    ask = parse_numeric(q.get("ask"))
    price = parse_numeric(q.get("price"))
    if bid and ask and price and price > 0:
        spread_pct = (ask - bid) / price
        if spread_pct > 0.015:
            score -= float(getattr(config, "day_wide_spread_penalty", 5.0))

    if bool(row.get("fallback_selected", False)):
        score -= float(getattr(config, "day_fallback_penalty", 5.0))
    if bool(row.get("legacy_top10_selected", False)):
        score += float(getattr(config, "day_legacy_top10_bonus", 2.0))
    if not is_etf:
        score += float(getattr(config, "day_non_etf_bonus", 5.0))

    intraday_weight = float(getattr(config, "day_intraday_strength_weight", 1.0))
    if is_etf:
        intraday_weight = float(getattr(config, "day_etf_intraday_strength_weight", intraday_weight))
    score += intraday_strength_score * intraday_weight

    volatility_penalty = _quote_volatility_penalty(
        q,
        start_pct=float(getattr(config, "day_volatility_penalty_start_pct", 8.0)),
        full_pct=float(getattr(config, "day_volatility_penalty_full_pct", 18.0)),
        max_penalty=float(getattr(config, "day_volatility_penalty_max", 8.0)),
    )
    if is_etf:
        volatility_penalty *= float(getattr(config, "day_etf_volatility_penalty_scale", 0.60))
    score -= volatility_penalty

    industry_score = _day_industry_trend_score(row, config)
    if is_etf:
        industry_score *= float(getattr(config, "day_etf_industry_trend_scale", 1.45))
    score += industry_score

    news_weight = float(config.news_day_weight)
    if is_etf:
        news_weight *= float(getattr(config, "day_etf_news_weight_scale", 1.35))
    score += _news_score_bonus(
        row,
        news_signal,
        weight=news_weight,
        market_fallback_ratio=config.news_market_fallback_ratio,
    )
    if is_etf:
        score += _day_etf_context_bonus(row, config, news_signal)
    score += global_signal_bonus_for_row(
        row,
        global_signal,
        config,
        strategy="T",
        news_signal=news_signal,
    )
    return score


def _day_momentum_alignment_multiplier(intraday_strength_score: float) -> float:
    normalized = (float(intraday_strength_score) + 2.0) / 8.0
    normalized = min(1.0, max(0.0, normalized))
    return 0.55 + (0.45 * normalized)


def _day_rank_group_bonus(
    rank: float,
    *,
    top_bonus: float,
    mid_bonus: float,
    lower_bonus: float,
    floor_bonus: float,
    top_cutoff: float,
    mid_cutoff: float,
    lower_cutoff: float,
    max_rank: float,
) -> float:
    normalized_rank = min(max(float(rank), 1.0), float(max_rank))
    if normalized_rank <= top_cutoff:
        return float(top_bonus)
    if normalized_rank <= mid_cutoff:
        return float(mid_bonus)
    if normalized_rank <= lower_cutoff:
        return float(lower_bonus)
    return float(floor_bonus)


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


def _day_intraday_structure_score(quote: Quote) -> float:
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


def _quote_volatility_penalty(
    quote: Quote,
    *,
    start_pct: float,
    full_pct: float,
    max_penalty: float,
) -> float:
    high_price = parse_numeric(quote.get("high"))
    low_price = parse_numeric(quote.get("low"))
    reference_price = parse_numeric(quote.get("open")) or parse_numeric(quote.get("price"))

    if (
        high_price is None
        or low_price is None
        or reference_price is None
        or high_price <= low_price
        or reference_price <= 0
        or max_penalty <= 0
    ):
        return 0.0

    range_pct = ((high_price - low_price) / reference_price) * 100.0
    start = max(0.0, float(start_pct))
    full = max(start + 1e-9, float(full_pct))
    if range_pct <= start:
        return 0.0

    penalty_ratio = min(1.0, (range_pct - start) / (full - start))
    return max(0.0, float(max_penalty)) * penalty_ratio


def _swing_structure_volume_weight(
    row: pd.Series,
    quote: Quote,
    config: TradeEngineConfig,
) -> float:
    participation_ratio = _quote_participation_ratio(row, quote)
    if participation_ratio is None:
        return 1.0

    start = max(0.0, float(getattr(config, "swing_structure_volume_ratio_start", 0.75)))
    full = max(start + 1e-9, float(getattr(config, "swing_structure_volume_ratio_full", 1.5)))
    floor = min(1.0, max(0.0, float(getattr(config, "swing_structure_volume_weight_floor", 0.7))))
    ceiling = max(1.0, float(getattr(config, "swing_structure_volume_weight_ceiling", 1.2)))

    if participation_ratio <= start:
        if start <= 1e-9:
            return floor
        return floor + (1.0 - floor) * min(1.0, participation_ratio / start)

    if participation_ratio >= full:
        return ceiling

    return 1.0 + (ceiling - 1.0) * ((participation_ratio - start) / (full - start))


def _quote_participation_ratio(row: pd.Series, quote: Quote) -> float | None:
    current_value = _pick_quote_numeric(quote, _QUOTE_VALUE_KEYS)
    if current_value is None:
        current_volume = _pick_quote_numeric(quote, _QUOTE_VOLUME_KEYS)
        price = parse_numeric(quote.get("price"))
        if current_volume is not None and price is not None and price > 0:
            current_value = current_volume * price

    baseline_value = parse_numeric(row.get("avg_value_5d")) or parse_numeric(row.get("avg_value_20d"))
    if current_value is not None and baseline_value is not None and baseline_value > 0:
        return max(0.0, current_value / baseline_value)

    current_volume = _pick_quote_numeric(quote, _QUOTE_VOLUME_KEYS)
    baseline_volume = parse_numeric(row.get("avg_volume_5d")) or parse_numeric(row.get("avg_volume_20d"))
    if current_volume is not None and baseline_volume is not None and baseline_volume > 0:
        return max(0.0, current_volume / baseline_volume)

    return None


def _pick_quote_numeric(quote: Quote, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = parse_numeric(quote.get(key))
        if value is not None:
            return value
    return None


def _linear_threshold_penalty(
    value_pct: float,
    *,
    start_pct: float,
    full_pct: float,
    max_penalty: float,
) -> float:
    if max_penalty <= 0:
        return 0.0

    start = max(0.0, float(start_pct))
    full = max(start + 1e-9, float(full_pct))
    if value_pct <= start:
        return 0.0

    penalty_ratio = min(1.0, (float(value_pct) - start) / (full - start))
    return max(0.0, float(max_penalty)) * penalty_ratio


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


def _day_etf_context_bonus(
    row: pd.Series,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None,
) -> float:
    score = 0.0

    if bool(row.get("sector_bucket_selected", False)):
        score += float(getattr(config, "day_etf_sector_bucket_bonus", 2.5))

    theme_sector = _clean_text(row.get("theme_sector"))
    if theme_sector:
        score += float(getattr(config, "day_etf_theme_sector_bonus", 3.5))

    if news_signal is None:
        return score

    sector_key = theme_sector or _clean_text(row.get("industry_bucket_name"))
    if sector_key:
        sector_score = float(news_signal.sector_scores.get(sector_key, 0.0))
        if sector_score > 0:
            score += min(
                float(getattr(config, "day_etf_positive_sector_news_bonus_max", 5.0)),
                sector_score * float(getattr(config, "day_etf_positive_sector_news_bonus_max", 5.0)),
            )
            if bool(row.get("sector_bucket_selected", False)):
                score += min(
                    float(getattr(config, "day_etf_positive_market_breadth_bonus_max", 2.0)),
                    max(0.0, float(news_signal.market_score))
                    * float(getattr(config, "day_etf_positive_market_breadth_bonus_max", 2.0)),
                )
    return score


def _resolve_change_pct(row: pd.Series, quotes: QuoteMap) -> float | None:
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


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"y", "yes", "true", "1", "etf"}


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()
