from __future__ import annotations

from backend.services.trading_engine.screeners import (
    etf_swing_screener,
    model_screener,
    popular_screener,
)
from backend.services.trading_engine.strategy import Candidates

from .trading_engine_support import FakeAPI, TradeEngineConfig


def test_strategy_and_screener_public_imports_remain_available() -> None:
    assert Candidates.__name__ == "Candidates"
    assert callable(popular_screener)
    assert callable(model_screener)
    assert callable(etf_swing_screener)


def test_public_screeners_preserve_empty_dataframe_columns_and_order() -> None:
    api = FakeAPI()
    asof = "20260213"

    popular = popular_screener(api, asof=asof, include_etf=False, config=TradeEngineConfig())
    model = model_screener(api, asof=asof, config=TradeEngineConfig())
    etf = etf_swing_screener(api, asof=asof, config=TradeEngineConfig())

    assert popular.empty
    assert list(popular.columns) == [
        "code",
        "name",
        "mcap",
        "avg_value_5d",
        "used_value_proxy",
        "asof_date",
        "volume_rank",
        "value_rank",
        "hts_view_rank",
        "master_market",
        "value_rank_5d_top10",
        "close",
        "change_pct",
        "is_etf",
        "fallback_selected",
        "sector_bucket_selected",
        "legacy_top10_selected",
        "theme_injected",
        "theme_sector",
        "industry_large_name",
        "industry_medium_name",
        "industry_small_name",
        "industry_bucket_code",
        "industry_bucket_name",
        "industry_close",
        "industry_ma5",
        "industry_ma20",
        "industry_day_change_pct",
        "industry_5d_change_pct",
        "market_warning_code",
        "management_issue_code",
        "retrace_from_high_10d_pct",
        "breakout_vs_prev_high_10d_pct",
    ]

    assert model.empty
    assert list(model.columns) == [
        "code",
        "name",
        "mcap",
        "avg_value_20d",
        "ma5",
        "ma20",
        "ma60",
        "ma120",
        "used_value_proxy",
        "asof_date",
        "close",
        "change_pct",
        "is_etf",
        "trend_tier",
        "industry_large_name",
        "industry_medium_name",
        "industry_small_name",
        "industry_bucket_code",
        "industry_bucket_name",
        "industry_close",
        "industry_ma5",
        "industry_ma20",
        "industry_day_change_pct",
        "industry_5d_change_pct",
        "market_warning_code",
        "management_issue_code",
    ]

    assert etf.empty
    assert list(etf.columns) == [
        "code",
        "name",
        "avg_value_20d",
        "ma5",
        "ma20",
        "ma60",
        "used_value_proxy",
        "asof_date",
        "close",
        "change_pct",
        "is_etf",
    ]
