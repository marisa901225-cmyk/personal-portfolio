from __future__ import annotations

import logging

import pandas as pd

from .config import TradeEngineConfig
from .industry_trend import enrich_industry_trend_fields
from .interfaces import TradingAPI
from .utils import normalize_code, parse_numeric

logger = logging.getLogger(__name__)


def _enrich_popular_industry_trend_fields(
    api: TradingAPI,
    df: pd.DataFrame,
    *,
    asof: str,
    config: TradeEngineConfig,
) -> pd.DataFrame:
    return enrich_industry_trend_fields(
        api,
        df,
        asof=asof,
        lookback_bars=config.day_industry_lookback_bars,
        log_prefix="popular_screener",
    )


def _enrich_quote_fields(
    api: TradingAPI,
    df: pd.DataFrame,
) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    working = df.copy()
    if "mcap" not in working.columns:
        working["mcap"] = None
    if "market_warning_code" not in working.columns:
        working["market_warning_code"] = None
    if "management_issue_code" not in working.columns:
        working["management_issue_code"] = None

    for idx, row in working.iterrows():
        code = normalize_code(row.get("code"))
        if not code:
            continue
        try:
            quote = api.quote(code)
        except Exception as exc:
            logger.warning("popular_screener quote failed code=%s error=%s", code, exc)
            continue
        if not bool(row.get("is_etf", False)):
            current_mcap = parse_numeric(row.get("mcap"))
            quote_mcap = parse_numeric(quote.get("market_cap"))
            if (current_mcap is None or current_mcap <= 0) and quote_mcap is not None and quote_mcap > 0:
                working.at[idx, "mcap"] = float(quote_mcap)
        quote_warning = str(quote.get("market_warning_code") or "").strip()
        if quote_warning:
            working.at[idx, "market_warning_code"] = quote_warning
        quote_management = str(quote.get("management_issue_code") or "").strip()
        if quote_management:
            working.at[idx, "management_issue_code"] = quote_management

    return working


def _enrich_popular_quote_fields(
    api: TradingAPI,
    df: pd.DataFrame,
) -> pd.DataFrame:
    return _enrich_quote_fields(api, df)


def _enrich_model_quote_fields(
    api: TradingAPI,
    df: pd.DataFrame,
) -> pd.DataFrame:
    return _enrich_quote_fields(api, df)
