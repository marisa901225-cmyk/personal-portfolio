from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .config import TradeEngineConfig
from .interfaces import TradingAPI
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
    popular = popular_screener(api, asof, include_etf=config.include_etf, config=config)
    model = model_screener(api, asof, include_etf=False, config=config)
    etf = etf_swing_screener(api, asof, config=config) if config.include_etf else pd.DataFrame()

    merged = _merge_candidates(popular, model, etf)
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


def pick_swing(candidates: Candidates, quotes: dict[str, dict[str, Any]], config: TradeEngineConfig) -> str | None:
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

    scored = primary.copy()
    scored["score"] = scored.apply(lambda r: _score_swing_row(r, quotes), axis=1)
    scored = scored.sort_values("score", ascending=False)
    if scored.empty:
        return None
    return str(scored.iloc[0]["code"])


def pick_daytrade(candidates: Candidates, quotes: dict[str, dict[str, Any]], config: TradeEngineConfig) -> str | None:
    pool = candidates.popular.copy()
    if pool.empty:
        return None

    if config.include_etf:
        pool = pool[
            (~pool["is_etf"].fillna(False))
            | (pool["avg_value_5d"].fillna(0) >= config.day_etf_min_avg_value_5d)
        ]

    if pool.empty:
        return None

    pool["score"] = pool.apply(lambda r: _score_day_row(r, quotes), axis=1)
    pool = pool.sort_values("score", ascending=False)
    if pool.empty:
        return None
    return str(pool.iloc[0]["code"])


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


def _score_swing_row(row: pd.Series, quotes: dict[str, dict[str, Any]]) -> float:
    code = str(row.get("code"))
    q = quotes.get(code, {})
    close = parse_numeric(q.get("price")) or parse_numeric(row.get("close")) or 0.0
    ma20 = parse_numeric(row.get("ma20"))
    ma60 = parse_numeric(row.get("ma60"))
    avg20 = parse_numeric(row.get("avg_value_20d")) or 0.0

    score = 0.0
    if bool(row.get("source_model", False)):
        score += 30.0

    if ma20 and close > ma20:
        score += 10.0
    if ma20 and ma60 and ma20 > ma60:
        score += 10.0

    score += min(20.0, max(0.0, avg20 / 100_000_000_000))

    if ma20 and ma20 > 0 and (close / ma20 - 1.0) > 0.08:
        score -= 20.0

    return score


def _score_day_row(row: pd.Series, quotes: dict[str, dict[str, Any]]) -> float:
    code = str(row.get("code"))
    q = quotes.get(code, {})

    score = 30.0
    score += min(20.0, (parse_numeric(row.get("avg_value_5d")) or 0.0) / 100_000_000_000)

    chg = parse_numeric(q.get("change_pct"))
    if chg is None:
        chg = parse_numeric(row.get("change_pct"))

    if chg is not None:
        if 0.5 <= chg <= 4.0:
            score += 10.0
        elif chg > 6.0:
            score -= 10.0

    bid = parse_numeric(q.get("bid"))
    ask = parse_numeric(q.get("ask"))
    price = parse_numeric(q.get("price"))
    if bid and ask and price and price > 0:
        spread_pct = (ask - bid) / price
        if spread_pct > 0.01:
            score -= 10.0

    if bool(row.get("fallback_selected", False)):
        score -= 5.0

    return score
