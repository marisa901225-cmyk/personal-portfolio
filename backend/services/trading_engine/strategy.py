from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .config import TradeEngineConfig
from .interfaces import TradingAPI
from .news_sentiment import NewsSentimentSignal
from .screeners import etf_swing_screener, model_screener, popular_screener
from .utils import parse_numeric


@dataclass(slots=True)
class Candidates:
    asof: str
    popular: pd.DataFrame
    model: pd.DataFrame
    etf: pd.DataFrame
    merged: pd.DataFrame
    quote_codes: list[str]



def build_candidates(api: TradingAPI, asof: str, config: TradeEngineConfig) -> Candidates:
    excluded_codes = _proxy_codes(config)
    popular = _drop_excluded_codes(
        popular_screener(api, asof, include_etf=config.include_etf, config=config),
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

    merged = _merge_candidates(popular, model, etf)
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


def fetch_quotes_subset(api: TradingAPI, codes: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for code in codes:
        try:
            out[code] = api.quote(code)
        except Exception:
            continue
    return out


def pick_swing(
    candidates: Candidates,
    quotes: dict[str, dict[str, Any]],
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> str | None:
    primary = candidates.model.copy()
    use_etf_fallback = primary.empty and config.allow_etf_swing_fallback
    if primary.empty and not use_etf_fallback:
        return None

    if use_etf_fallback:
        primary = candidates.etf.copy()
        if primary.empty:
            return None
        primary["source_model"] = False
    else:
        primary["source_model"] = True

    if primary.empty:
        return None

    primary["_change_pct_num"] = primary.apply(lambda r: _resolve_change_pct(r, quotes), axis=1)
    primary = primary[
        primary["_change_pct_num"].isna()
        | (primary["_change_pct_num"] > float(config.swing_hard_drop_exclude_pct))
    ]
    if primary.empty:
        return None

    if use_etf_fallback:
        primary = primary[
            primary["_change_pct_num"].isna()
            | (primary["_change_pct_num"] >= float(config.swing_etf_fallback_min_change_pct))
        ]
        if primary.empty:
            return None

    scored = primary.copy()
    if news_signal is None:
        scored["score"] = scored.apply(lambda r: _score_swing_row(r, quotes, config), axis=1)
    else:
        scored["score"] = scored.apply(lambda r: _score_swing_row(r, quotes, config, news_signal), axis=1)
    scored = scored.sort_values("score", ascending=False)
    if scored.empty:
        return None
    return str(scored.iloc[0]["code"])


def pick_daytrade(
    candidates: Candidates,
    quotes: dict[str, dict[str, Any]],
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None = None,
) -> str | None:
    ranked_codes = rank_daytrade_codes(candidates, quotes, config, news_signal=news_signal)
    return ranked_codes[0] if ranked_codes else None


def rank_daytrade_codes(
    candidates: Candidates,
    quotes: dict[str, dict[str, Any]],
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
    pool["_change_pct_num"] = (
        pool["change_pct"].map(parse_numeric)
        if "change_pct" in pool.columns
        else None
    )

    if config.include_etf:
        pool = pool[
            (~pool["_is_etf"])
            | (pool["_avg_value_5d_num"].fillna(0) >= config.day_etf_min_avg_value_5d)
        ]
    else:
        pool = pool[~pool["_is_etf"]]

    if pool.empty:
        return []

    pool["_live_change_pct_num"] = pool.apply(lambda r: _resolve_change_pct(r, quotes), axis=1)
    pool = pool[
        pool["_live_change_pct_num"].isna()
        | (pool["_live_change_pct_num"] > float(config.day_hard_drop_exclude_pct))
    ]
    if pool.empty:
        return []

    if news_signal is None:
        pool["score"] = pool.apply(lambda r: _score_day_row(r, quotes, config), axis=1)
    else:
        pool["score"] = pool.apply(lambda r: _score_day_row(r, quotes, config, news_signal), axis=1)
    # 동점 시 거래대금보다 상승률(모멘텀)이 중요하므로 2차 정렬 기준 추가
    pool = pool.sort_values(
        by=["score", "_live_change_pct_num", "_avg_value_5d_num"],
        ascending=[False, False, False]
    )
    if pool.empty:
        return []

    stock_pool = pool[~pool["_is_etf"]]
    etf_pool = pool[pool["_is_etf"]]

    ordered_codes: list[str] = []

    if not stock_pool.empty and not etf_pool.empty:
        best_stock = stock_pool.iloc[0]
        best_etf = etf_pool.iloc[0]
        if best_stock["score"] >= best_etf["score"] * config.day_stock_prefer_threshold:
            ordered_frames = [stock_pool, etf_pool]
        else:
            ordered_frames = [etf_pool, stock_pool]
    elif not stock_pool.empty:
        ordered_frames = [stock_pool]
    elif not etf_pool.empty:
        ordered_frames = [etf_pool]
    else:
        ordered_frames = []

    for frame in ordered_frames:
        ordered_codes.extend([str(code) for code in frame["code"].tolist()])

    deduped_codes: list[str] = []
    seen: set[str] = set()
    for code in ordered_codes:
        if code in seen:
            continue
        seen.add(code)
        deduped_codes.append(code)

    return deduped_codes


def _merge_candidates(popular: pd.DataFrame, model: pd.DataFrame, etf: pd.DataFrame) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []

    if not popular.empty:
        p = popular[["code", "name", "avg_value_5d", "close", "change_pct", "is_etf"]].copy()
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
    # 존재하는 컬럼만 기준으로 정렬 (popular만 있을 경우 avg_value_20d가 없음)
    sort_cols = [c for c in ["avg_value_20d", "avg_value_5d"] if c in merged.columns]
    if sort_cols:
        merged = merged.sort_values(
            by=sort_cols,
            ascending=False,
            na_position="last",
        )
    merged = merged.drop_duplicates(subset=["code"], keep="first").reset_index(drop=True)
    return merged


def _build_quote_codes(merged: pd.DataFrame, limit: int) -> list[str]:
    if merged.empty:
        return []
    top = merged.head(max(1, int(limit)))
    return [str(c) for c in top["code"].tolist()]


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
            score += min(float(config.swing_momentum_bonus_max), float(config.swing_momentum_bonus_max) * (chg / cap_pct))
        else:
            penalty_cap = max(abs(float(config.swing_hard_drop_exclude_pct)), cap_pct, 1.0)
            penalty_ratio = min(1.0, abs(chg) / penalty_cap)
            score -= float(config.swing_negative_penalty_max) * penalty_ratio

    score += _news_score_bonus(
        row,
        news_signal,
        weight=config.news_swing_weight,
        market_fallback_ratio=config.news_market_fallback_ratio,
    )

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

    chg = _resolve_change_pct(row, quotes)

    if chg is not None:
        cap_pct = max(config.day_momentum_bonus_cap_pct, 1e-9)
        if 0.5 <= chg <= cap_pct:
            score += config.day_momentum_bonus_max * (chg / cap_pct)
        elif chg > 20.0:        # 20% 이상 급등은 너무 늦음 (리스크)
            score -= 10.0
        elif chg < 0:           # 하락세인 종목은 감점 (떨어지는 칼날 회피)
            score -= min(
                float(config.day_negative_penalty_max),
                abs(float(chg)) * float(config.day_negative_penalty_per_pct),
            )

    bid = parse_numeric(q.get("bid"))
    ask = parse_numeric(q.get("ask"))
    price = parse_numeric(q.get("price"))
    if bid and ask and price and price > 0:
        spread_pct = (ask - bid) / price
        if spread_pct > 0.015:  # 1% -> 1.5% 완화 (중소형주 호가 공백 감안)
            score -= 5.0        # 감점 폭도 -10 -> -5로 완화

    if bool(row.get("fallback_selected", False)):
        score -= 5.0
    
    # ETF가 아닌 개별 주식에 가산점 부여 (알파 추구)
    if not _to_bool(row.get("_is_etf", row.get("is_etf", False))):
        score += 5.0

    score += _news_score_bonus(
        row,
        news_signal,
        weight=config.news_day_weight,
        market_fallback_ratio=config.news_market_fallback_ratio,
    )

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


def _proxy_codes(config: TradeEngineConfig) -> set[str]:
    codes = {str(config.market_proxy_code).strip(), str(config.kosdaq_proxy_code).strip()}
    return {c for c in codes if c}


def _drop_excluded_codes(df: pd.DataFrame, excluded_codes: set[str]) -> pd.DataFrame:
    if df.empty or "code" not in df.columns or not excluded_codes:
        return df
    out = df.loc[~df["code"].astype(str).isin(excluded_codes)].copy()
    return out.reset_index(drop=True)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)
