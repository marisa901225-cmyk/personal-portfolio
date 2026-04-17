from __future__ import annotations

from datetime import datetime, timedelta
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.core.models_misc import (
    TradingEngineIndustrySyncState,
    TradingEngineStockIndustry,
)
from backend.services.trading_engine.bot import HybridTradingBot
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.execution import exit_position
from backend.services.trading_engine.industry_master import (
    StockIndustryInfo,
    load_stock_industry_db_map,
    resolve_stock_industry_info,
)
from backend.services.trading_engine.market_calendar import get_last_trading_day, is_trading_day
from backend.services.trading_engine.news_sentiment import NewsSentimentSignal
from backend.services.trading_engine.regime import detect_intraday_circuit_breaker, get_regime
from backend.services.trading_engine.risk import can_enter, should_exit_position
from backend.services.trading_engine.runtime import _load_config_from_env
from backend.services.trading_engine.stock_master import StockMasterInfo, load_swing_universe_candidates
from backend.services.trading_engine.strategy import Candidates, pick_swing, rank_daytrade_codes
from backend.services.trading_engine.screeners import etf_swing_screener, model_screener, popular_screener
from backend.services.trading_engine.state import (
    PositionState,
    get_day_stoploss_fail_count,
    get_day_stoploss_excluded_codes,
    get_swing_time_excluded_codes,
    load_state,
    new_state,
    record_day_stoploss_failure,
    save_state,
)


class FakeAPI:
    def __init__(self) -> None:
        self._volume_rank: dict[tuple[str, str], list[dict]] = {}
        self._market_cap_rank: dict[str, list[dict]] = {}
        self._bars: dict[tuple[str, str], pd.DataFrame] = {}
        self._index_bars: dict[tuple[str, str], pd.DataFrame] = {}
        self._quotes: dict[str, dict] = {}
        self._positions: list[dict] = []
        self._cash_available: int = 1_000_000
        self.order_calls: list[dict] = []

    def volume_rank(self, kind: str, top_n: int, asof: str) -> list[dict]:
        del top_n
        return list(self._volume_rank.get((kind, asof), []))

    def market_cap_rank(self, top_k: int, asof: str) -> list[dict]:
        del top_k
        return list(self._market_cap_rank.get(asof, []))

    def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
        del lookback
        return self._bars.get((code, end), pd.DataFrame())

    def daily_index_bars(self, index_code: str, end: str, lookback: int) -> pd.DataFrame:
        del lookback
        return self._index_bars.get((index_code, end), pd.DataFrame())

    def quote(self, code: str) -> dict:
        return dict(self._quotes.get(code, {"price": 0, "change_pct": 0.0}))

    def positions(self) -> list[dict]:
        return list(self._positions)

    def cash_available(self) -> int:
        return self._cash_available

    def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
        self.order_calls.append(
            {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
        )
        return {"order_id": f"{side}-{code}", "filled_qty": qty, "avg_price": price or self.quote(code).get("price", 0)}

    def open_orders(self) -> list[dict]:
        return []

    def cancel_order(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": "cancelled"}


def _make_bars(asof: str, n: int, start_close: float, step: float, value: float | None = None) -> pd.DataFrame:
    end = datetime.strptime(asof, "%Y%m%d")
    rows = []
    close = start_close
    for i in range(n):
        day = end - timedelta(days=n - i - 1)
        row = {
            "date": day.strftime("%Y%m%d"),
            "close": close,
            "volume": 1_000_000,
        }
        if value is not None:
            row["value"] = value
        rows.append(row)
        close += step
    return pd.DataFrame(rows)


def _make_bars_from_closes(asof: str, closes: list[float], value: float | None = None) -> pd.DataFrame:
    end = datetime.strptime(asof, "%Y%m%d")
    start = end - timedelta(days=len(closes) - 1)
    rows = []
    for offset, close in enumerate(closes):
        day = start + timedelta(days=offset)
        row = {
            "date": day.strftime("%Y%m%d"),
            "close": close,
            "volume": 1_000_000,
        }
        if value is not None:
            row["value"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _make_intraday_bars(
    asof: str,
    closes: list[float],
    *,
    start_time: str = "090000",
    last_change_pct: float | None = None,
) -> pd.DataFrame:
    base = datetime.strptime(asof + start_time, "%Y%m%d%H%M%S")
    rows: list[dict] = []
    for idx, close in enumerate(closes):
        ts = base + timedelta(minutes=idx)
        row = {
            "date": ts.strftime("%Y%m%d"),
            "time": ts.strftime("%H%M%S"),
            "timestamp": ts.strftime("%Y%m%d%H%M%S"),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
        }
        if last_change_pct is not None and idx == len(closes) - 1:
            row["change_pct"] = last_change_pct
        rows.append(row)
    return pd.DataFrame(rows)


def test_popular_screener_intersection_and_proxy() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
        {"code": "000002", "name": "Beta", "rank": 2},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
        {"code": "000003", "name": "Gamma", "rank": 2},
    ]
    api._bars[("000001", asof)] = _make_bars(asof, 10, 100, 1, value=None)  # proxy path
    api._bars[("000002", asof)] = _make_bars(asof, 10, 90, 0, value=20_000_000_000)
    api._bars[("000003", asof)] = _make_bars(asof, 10, 80, 0, value=10_000_000_000)

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
        ),
    )

    assert not out.empty
    assert "000001" in set(out["code"])
    row = out[out["code"] == "000001"].iloc[0]
    assert bool(row["used_value_proxy"]) is True


@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
def test_model_screener_filters_etf_and_applies_ma_chain(mock_load_universe) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_universe.return_value = [
        {"code": "111111", "name": "GoodStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "222222", "name": "KODEX ETF", "mcap": 3_000_000_000_000, "is_etf": True},
    ]
    api._bars[("111111", asof)] = _make_bars(asof, 140, 100, 1, value=700_000_000_000)
    api._bars[("222222", asof)] = _make_bars(asof, 140, 100, 1, value=900_000_000_000)

    out = model_screener(api, asof=asof)

    assert not out.empty
    assert set(out["code"]) == {"111111"}


@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
def test_model_screener_allows_relaxed_large_cap_from_master_universe(mock_load_universe) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_universe.return_value = [
        {"code": "333333", "name": "LargeCapNoMetric", "mcap": 1_200_000_000_000, "is_etf": False},
    ]
    api._bars[("333333", asof)] = _make_bars(asof, 100, 100, 1, value=900_000_000_000)

    out = model_screener(api, asof=asof)

    assert not out.empty
    row = out[out["code"] == "333333"].iloc[0]
    assert row["trend_tier"] == "relaxed"


@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
def test_model_screener_enriches_industry_index_trend_fields(
    mock_load_universe,
    mock_load_industry_map,
) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_universe.return_value = [
        {"code": "111111", "name": "GoodStock", "mcap": 2_000_000_000_000, "is_etf": False},
    ]
    api._bars[("111111", asof)] = _make_bars(asof, 140, 100, 1, value=700_000_000_000)
    api._index_bars[("2250", asof)] = _make_bars(asof, 60, 800, 3)
    mock_load_industry_map.return_value = {
        "111111": StockIndustryInfo(
            code="111111",
            name="GoodStock",
            market="KOSDAQ",
            large_code="1014",
            large_name="금융",
            medium_code="2240",
            medium_name="창업투자",
            small_code="2250",
            small_name="창업투자",
        )
    }

    out = model_screener(api, asof=asof)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["industry_bucket_code"] == "2250"
    assert row["industry_bucket_name"] == "창업투자"
    assert float(row["industry_5d_change_pct"]) > 0
    assert float(row["industry_ma20"]) > 0


@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_model_screener_filters_live_management_warning_risk_candidates(
    mock_load_industry_map,
    mock_load_universe,
) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}
    mock_load_universe.return_value = [
        {"code": "OK001", "name": "GoodStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "WARN01", "name": "WarnStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "RISK01", "name": "RiskStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "MGMT01", "name": "MgmtStock", "mcap": 2_000_000_000_000, "is_etf": False},
    ]
    for code in ("OK001", "WARN01", "RISK01", "MGMT01"):
        api._bars[(code, asof)] = _make_bars(asof, 140, 100, 1, value=150_000_000_000)
    api._quotes.update(
        {
            "OK001": {"market_warning_code": "00", "management_issue_code": "N"},
            "WARN01": {"market_warning_code": "02", "management_issue_code": "N"},
            "RISK01": {"market_warning_code": "03", "management_issue_code": "N"},
            "MGMT01": {"market_warning_code": "00", "management_issue_code": "Y"},
        }
    )

    out = model_screener(api, asof=asof)

    assert list(out["code"]) == ["OK001"]


@patch("backend.services.trading_engine.stock_master.load_stock_master_map")
def test_load_swing_universe_candidates_prefers_index_members_and_near_cutoff_large_caps(
    mock_load_stock_master_map,
) -> None:
    mock_load_stock_master_map.return_value = {
        "AAA111": StockMasterInfo(
            code="AAA111",
            name="KOSPI200 Member",
            market="KOSPI",
            master_market_cap=2_000_000_000_000,
            listed_shares=10_000_000,
            base_price=200_000,
            is_etf=False,
            is_kospi200=True,
            is_kosdaq150=False,
        ),
        "BBB222": StockMasterInfo(
            code="BBB222",
            name="Near KOSPI Cutoff",
            market="KOSPI",
            master_market_cap=1_050_000_000_000,
            listed_shares=10_000_000,
            base_price=105_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
        "CCC333": StockMasterInfo(
            code="CCC333",
            name="KOSDAQ150 Member",
            market="KOSDAQ",
            master_market_cap=650_000_000_000,
            listed_shares=10_000_000,
            base_price=65_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=True,
        ),
        "DDD444": StockMasterInfo(
            code="DDD444",
            name="Near KOSDAQ Cutoff",
            market="KOSDAQ",
            master_market_cap=590_000_000_000,
            listed_shares=10_000_000,
            base_price=59_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
        "EEE555": StockMasterInfo(
            code="EEE555",
            name="Too Small",
            market="KOSDAQ",
            master_market_cap=300_000_000_000,
            listed_shares=10_000_000,
            base_price=30_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
        "ETF999": StockMasterInfo(
            code="ETF999",
            name="KODEX ETF",
            market="KOSPI",
            master_market_cap=2_500_000_000_000,
            listed_shares=10_000_000,
            base_price=250_000,
            is_etf=True,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
    }
    cfg = TradeEngineConfig(model_top_k=10, model_mcap_min=1_000_000_000_000)

    rows = load_swing_universe_candidates(cfg)
    codes = [str(row["code"]) for row in rows]

    assert codes[:4] == ["AAA111", "CCC333", "BBB222", "DDD444"]
    assert "EEE555" not in codes
    assert "ETF999" not in codes


def test_etf_swing_screener_excludes_broad_market_index_etfs() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "379800", "name": "KODEX 미국S&P500", "rank": 1, "is_etf": True},
        {"code": "091230", "name": "TIGER 반도체", "rank": 2, "is_etf": True},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "379800", "name": "KODEX 미국S&P500", "rank": 1, "is_etf": True},
        {"code": "091230", "name": "TIGER 반도체", "rank": 2, "is_etf": True},
    ]
    api._bars[("379800", asof)] = _make_bars(asof, 80, 100, 0.5, value=200_000_000_000)
    api._bars[("091230", asof)] = _make_bars(asof, 80, 90, 0.6, value=250_000_000_000)

    out = etf_swing_screener(api, asof=asof)

    assert not out.empty
    assert "379800" not in set(out["code"])
    assert "091230" in set(out["code"])


def test_popular_screener_injects_theme_candidate_from_strong_news_sector() -> None:
    asof = "20260213"
    api = FakeAPI()

    base_rows = []
    for idx in range(10):
        code = f"{100001 + idx:06d}"
        base_rows.append({"code": code, "name": f"일반주{idx + 1}", "rank": idx + 1})
        api._bars[(code, asof)] = _make_bars(asof, 10, 100, 0, value=100_000_000_000 - (idx * 5_000_000_000))

    theme_code = "777777"
    themed = {"code": theme_code, "name": "한싹", "rank": 11}
    api._bars[(theme_code, asof)] = _make_bars(asof, 10, 90, 0, value=35_000_000_000)

    api._volume_rank[("volume", asof)] = [*base_rows, themed]
    api._volume_rank[("value", asof)] = [*base_rows, themed]

    cfg = TradeEngineConfig(
        popular_sector_top_n=0,
        popular_final_top_n=10,
        day_theme_candidate_injection_enabled=True,
        day_theme_candidate_max_injections=2,
        day_theme_candidate_min_sector_score=0.4,
        day_theme_candidate_min_avg_value_5d=30_000_000_000,
    )
    news_signal = NewsSentimentSignal(
        market_score=0.2,
        sector_scores={"cyber_security": 0.8},
        sector_keywords={"cyber_security": ("한싹", "보안")},
        article_count=30,
    )

    out = popular_screener(api, asof=asof, include_etf=False, config=cfg, news_signal=news_signal)

    assert len(out) == 11
    assert theme_code in set(out["code"])
    theme_row = out[out["code"] == theme_code].iloc[0]
    assert bool(theme_row["theme_injected"]) is True
    assert theme_row["theme_sector"] == "cyber_security"


def test_popular_screener_does_not_inject_theme_candidate_when_sector_score_is_weak() -> None:
    asof = "20260213"
    api = FakeAPI()

    base_rows = []
    for idx in range(10):
        code = f"{200001 + idx:06d}"
        base_rows.append({"code": code, "name": f"일반주{idx + 1}", "rank": idx + 1})
        api._bars[(code, asof)] = _make_bars(asof, 10, 100, 0, value=100_000_000_000 - (idx * 5_000_000_000))

    theme_code = "888888"
    themed = {"code": theme_code, "name": "드림시큐리티", "rank": 11}
    api._bars[(theme_code, asof)] = _make_bars(asof, 10, 90, 0, value=35_000_000_000)

    api._volume_rank[("volume", asof)] = [*base_rows, themed]
    api._volume_rank[("value", asof)] = [*base_rows, themed]

    cfg = TradeEngineConfig(
        popular_sector_top_n=0,
        popular_final_top_n=10,
        day_theme_candidate_injection_enabled=True,
        day_theme_candidate_max_injections=2,
        day_theme_candidate_min_sector_score=0.4,
        day_theme_candidate_min_avg_value_5d=30_000_000_000,
    )
    news_signal = NewsSentimentSignal(
        market_score=0.2,
        sector_scores={"cyber_security": 0.25},
        sector_keywords={"cyber_security": ("드림시큐리티", "보안")},
        article_count=30,
    )

    out = popular_screener(api, asof=asof, include_etf=False, config=cfg, news_signal=news_signal)

    assert len(out) == 10
    assert theme_code not in set(out["code"])


def test_popular_screener_keeps_sector_bucket_and_legacy_top10_together() -> None:
    asof = "20260213"
    api = FakeAPI()

    legacy_rows = []
    for idx in range(10):
        code = f"{300001 + idx:06d}"
        legacy_rows.append({"code": code, "name": f"일반주{idx + 1}", "rank": idx + 1})
        api._bars[(code, asof)] = _make_bars(
            asof,
            10,
            100,
            0,
            value=120_000_000_000 - (idx * 5_000_000_000),
        )

    sector_rows = [
        {"code": "399991", "name": "창투에이스", "rank": 11},
        {"code": "399992", "name": "태양광리더", "rank": 12},
    ]
    api._bars[("399991", asof)] = _make_bars(asof, 10, 90, 0, value=45_000_000_000)
    api._bars[("399992", asof)] = _make_bars(asof, 10, 85, 0, value=42_000_000_000)

    api._volume_rank[("volume", asof)] = [*legacy_rows, *sector_rows]
    api._volume_rank[("value", asof)] = [*legacy_rows, *sector_rows]

    cfg = TradeEngineConfig(
        popular_sector_top_n=1,
        popular_final_top_n=10,
    )
    news_signal = NewsSentimentSignal(
        market_score=0.1,
        sector_scores={
            "venture_capital": 0.8,
            "solar": 0.7,
        },
        sector_keywords={
            "venture_capital": ("창투",),
            "solar": ("태양광",),
        },
        article_count=12,
    )

    out = popular_screener(api, asof=asof, include_etf=False, config=cfg, news_signal=news_signal)

    assert "399991" in set(out["code"])
    assert "399992" in set(out["code"])
    assert bool(out[out["code"] == "399991"].iloc[0]["sector_bucket_selected"]) is True
    assert bool(out[out["code"] == "399991"].iloc[0]["legacy_top10_selected"]) is False
    assert bool(out[out["code"] == "300001"].iloc[0]["legacy_top10_selected"]) is True


@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_uses_db_industry_bucket_when_available(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()

    api._volume_rank[("volume", asof)] = [
        {"code": "410001", "name": "AlphaOne", "rank": 1},
        {"code": "410002", "name": "BetaTwo", "rank": 2},
        {"code": "410003", "name": "GammaThree", "rank": 3},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "410001", "name": "AlphaOne", "rank": 1},
        {"code": "410002", "name": "BetaTwo", "rank": 2},
        {"code": "410003", "name": "GammaThree", "rank": 3},
    ]
    api._bars[("410001", asof)] = _make_bars(asof, 10, 100, 0, value=90_000_000_000)
    api._bars[("410002", asof)] = _make_bars(asof, 10, 90, 0, value=60_000_000_000)
    api._bars[("410003", asof)] = _make_bars(asof, 10, 80, 0, value=50_000_000_000)

    mock_load_industry_map.return_value = {
        "410001": StockIndustryInfo(
            code="410001",
            name="AlphaOne",
            market="KOSDAQ",
            large_code="0027",
            large_name="제조",
            medium_code="0013",
            medium_name="전기·전자",
            small_code=None,
            small_name=None,
        ),
        "410002": StockIndustryInfo(
            code="410002",
            name="BetaTwo",
            market="KOSDAQ",
            large_code="1014",
            large_name="금융",
            medium_code=None,
            medium_name=None,
            small_code=None,
            small_name=None,
        ),
        "410003": StockIndustryInfo(
            code="410003",
            name="GammaThree",
            market="KOSDAQ",
            large_code="0027",
            large_name="제조",
            medium_code="0013",
            medium_name="전기·전자",
            small_code=None,
            small_name=None,
        ),
    }

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=1,
            popular_final_top_n=1,
        ),
    )

    assert "410001" in set(out["code"])
    assert "410002" in set(out["code"])
    assert bool(out[out["code"] == "410002"].iloc[0]["sector_bucket_selected"]) is True
    assert out[out["code"] == "410002"].iloc[0]["industry_bucket_name"] == "금융"


@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_enriches_industry_index_trend_fields(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "410010", "name": "VentureAlpha", "rank": 1},
    ]
    api._volume_rank[("value", asof)] = list(api._volume_rank[("volume", asof)])
    api._bars[("410010", asof)] = _make_bars(asof, 10, 100, 1, value=90_000_000_000)
    api._index_bars[("2250", asof)] = _make_bars(asof, 30, 800, 4)

    mock_load_industry_map.return_value = {
        "410010": StockIndustryInfo(
            code="410010",
            name="VentureAlpha",
            market="KOSDAQ",
            large_code="1014",
            large_name="금융",
            medium_code="2240",
            medium_name="창업투자",
            small_code="2250",
            small_name="창업투자",
        )
    }

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
        ),
    )

    assert len(out) == 1
    row = out.iloc[0]
    assert row["industry_bucket_code"] == "2250"
    assert row["industry_bucket_name"] == "창업투자"
    assert float(row["industry_day_change_pct"]) > 0
    assert float(row["industry_ma20"]) > 0


@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_applies_default_day_stock_liquidity_floor(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}

    api._volume_rank[("volume", asof)] = [
        {"code": "431001", "name": "BelowFloor", "rank": 1},
        {"code": "431002", "name": "AboveFloor", "rank": 2},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "431001", "name": "BelowFloor", "rank": 1},
        {"code": "431002", "name": "AboveFloor", "rank": 2},
    ]
    api._bars[("431001", asof)] = _make_bars(asof, 10, 100, 0, value=9_000_000_000)
    api._bars[("431002", asof)] = _make_bars(asof, 10, 100, 0, value=12_000_000_000)
    api._quotes["431001"] = {"price": 10000, "change_pct": 2.0, "market_cap": 1_200_000_000_000}
    api._quotes["431002"] = {"price": 10000, "change_pct": 2.0, "market_cap": 1_200_000_000_000}

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=0,
            popular_final_top_n=10,
        ),
    )

    assert "431001" not in set(out["code"])
    assert "431002" in set(out["code"])


@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_filters_small_stock_by_mcap_floor(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}

    api._volume_rank[("volume", asof)] = [
        {"code": "430001", "name": "SmallCap", "rank": 1},
        {"code": "430002", "name": "LargeCap", "rank": 2},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "430001", "name": "SmallCap", "rank": 1},
        {"code": "430002", "name": "LargeCap", "rank": 2},
    ]
    api._bars[("430001", asof)] = _make_bars(asof, 10, 100, 0, value=60_000_000_000)
    api._bars[("430002", asof)] = _make_bars(asof, 10, 100, 0, value=60_000_000_000)
    api._quotes["430001"] = {"price": 10000, "change_pct": 2.0, "market_cap": 400_000_000_000}
    api._quotes["430002"] = {"price": 10000, "change_pct": 2.0, "market_cap": 1_200_000_000_000}

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=0,
            popular_final_top_n=10,
            day_stock_min_avg_value_5d=30_000_000_000,
            day_stock_min_mcap=1_000_000_000_000,
        ),
    )

    assert "430001" not in set(out["code"])
    assert "430002" in set(out["code"])


@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_filters_live_management_warning_risk_candidates(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}

    api._volume_rank[("volume", asof)] = [
        {"code": "440001", "name": "관리종목", "rank": 1},
        {"code": "440002", "name": "투경종목", "rank": 2},
        {"code": "440003", "name": "투위험종목", "rank": 3},
        {"code": "440004", "name": "정상종목", "rank": 4},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "440001", "name": "관리종목", "rank": 1},
        {"code": "440002", "name": "투경종목", "rank": 2},
        {"code": "440003", "name": "투위험종목", "rank": 3},
        {"code": "440004", "name": "정상종목", "rank": 4},
    ]
    for code in ("440001", "440002", "440003", "440004"):
        api._bars[(code, asof)] = _make_bars(asof, 10, 100, 0, value=60_000_000_000)

    api._quotes["440001"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "Y",
        "market_warning_code": "00",
    }
    api._quotes["440002"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "N",
        "market_warning_code": "02",
    }
    api._quotes["440003"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "N",
        "market_warning_code": "03",
    }
    api._quotes["440004"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "N",
        "market_warning_code": "00",
    }

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=0,
            popular_final_top_n=10,
            day_stock_min_avg_value_5d=30_000_000_000,
            day_stock_min_mcap=1_000_000_000_000,
        ),
    )

    assert set(out["code"]) == {"440004"}


@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_does_not_stringify_missing_industry_bucket(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()

    api._volume_rank[("volume", asof)] = [
        {"code": "420001", "name": "드림시큐리티", "rank": 1},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "420001", "name": "드림시큐리티", "rank": 1},
    ]
    api._bars[("420001", asof)] = _make_bars(asof, 10, 100, 0, value=55_000_000_000)
    mock_load_industry_map.return_value = {}

    news_signal = NewsSentimentSignal(
        market_score=0.1,
        sector_scores={"cyber_security": 0.8},
        sector_keywords={"cyber_security": ("드림시큐리티", "보안")},
        article_count=8,
    )

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(popular_sector_top_n=1, popular_final_top_n=0),
        news_signal=news_signal,
    )

    row = out[out["code"] == "420001"].iloc[0]
    assert row["industry_bucket_name"] == "cyber_security"


def test_resolve_stock_industry_info_parses_master_zips(tmp_path) -> None:
    idx_zip = tmp_path / "idxcode.mst.zip"
    kospi_zip = tmp_path / "kospi_code.mst.zip"
    kosdaq_zip = tmp_path / "kosdaq_code.mst.zip"

    _write_idx_master_zip(
        idx_zip,
        {
            "0027": "제조",
            "0013": "전기·전자",
            "1014": "금융",
        },
    )
    _write_stock_master_zip(
        kospi_zip,
        member_name="kospi_code.mst",
        tail_width=227,
        rows=[
            ("005930", "삼성전자", "0027", "0013", "0000"),
        ],
    )
    _write_stock_master_zip(
        kosdaq_zip,
        member_name="kosdaq_code.mst",
        tail_width=221,
        rows=[
            ("027360", "아주IB투자", "1014", "0000", "0000"),
        ],
    )

    samsung = resolve_stock_industry_info(
        "005930",
        idxcode_path=str(idx_zip),
        kospi_master_path=str(kospi_zip),
        kosdaq_master_path=str(kosdaq_zip),
    )
    venture = resolve_stock_industry_info(
        "027360",
        idxcode_path=str(idx_zip),
        kospi_master_path=str(kospi_zip),
        kosdaq_master_path=str(kosdaq_zip),
    )

    assert samsung is not None
    assert samsung.market == "KOSPI"
    assert samsung.large_name == "제조"
    assert samsung.medium_name == "전기·전자"
    assert samsung.bucket_name == "전기·전자"
    assert venture is not None
    assert venture.market == "KOSDAQ"
    assert venture.large_name == "금융"
    assert venture.bucket_name == "금융"


def test_load_stock_industry_db_map_syncs_from_master_zips(tmp_path) -> None:
    idx_zip = tmp_path / "idxcode.mst.zip"
    kospi_zip = tmp_path / "kospi_code.mst.zip"
    kosdaq_zip = tmp_path / "kosdaq_code.mst.zip"

    _write_idx_master_zip(
        idx_zip,
        {
            "0027": "제조",
            "0013": "전기·전자",
        },
    )
    _write_stock_master_zip(
        kospi_zip,
        member_name="kospi_code.mst",
        tail_width=227,
        rows=[
            ("005930", "삼성전자", "0027", "0013", "0000"),
        ],
    )
    _write_stock_master_zip(
        kosdaq_zip,
        member_name="kosdaq_code.mst",
        tail_width=221,
        rows=[
            ("011930", "신성이엔지", "0027", "0013", "0000"),
        ],
    )

    test_engine = create_engine("sqlite:///:memory:", future=True)
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)

    with (
        patch("backend.services.trading_engine.industry_master.engine", test_engine),
        patch("backend.services.trading_engine.industry_master.SessionLocal", TestSessionLocal),
    ):
        industry_map = load_stock_industry_db_map(
            idxcode_path=str(idx_zip),
            kospi_master_path=str(kospi_zip),
            kosdaq_master_path=str(kosdaq_zip),
        )

        assert "005930" in industry_map
        assert "011930" in industry_map
        assert industry_map["011930"].bucket_name == "전기·전자"

        with TestSessionLocal() as db:
            sync_state = db.get(TradingEngineIndustrySyncState, "stock_master")
            rows = db.execute(select(TradingEngineStockIndustry)).scalars().all()

        assert sync_state is not None
        assert sync_state.row_count == 2
        assert {row.code for row in rows} == {"005930", "011930"}


def test_market_calendar_fallback_uses_proxy_etf_bars() -> None:
    api = FakeAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [
            {"date": "20260212", "close": 100, "volume": 1},
            {"date": "20260213", "close": 101, "volume": 1},
        ]
    )
    api._bars[("069500", "20260213")] = pd.DataFrame(
        [
            {"date": "20260213", "close": 101, "volume": 1},
        ]
    )

    assert is_trading_day(api, "20260214") is False
    assert get_last_trading_day(api, "20260214") == "20260213"


def _write_idx_master_zip(path, rows: dict[str, str]) -> None:
    payload = "\n".join(f"0{code}{name}" for code, name in rows.items())
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("idxcode.mst", payload.encode("cp949"))


def _write_stock_master_zip(path, *, member_name: str, tail_width: int, rows: list[tuple[str, str, str, str, str]]) -> None:
    payload_rows: list[str] = []
    for code, name, large_code, medium_code, small_code in rows:
        prefix = f"{code:<9}{'':12}{name}"
        suffix = f"000{large_code}{medium_code}{small_code}".ljust(tail_width, "0")
        payload_rows.append(prefix + suffix)
    payload = "\n".join(payload_rows)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(member_name, payload.encode("cp949"))


def test_bot_passes_on_holiday_without_order(tmp_path) -> None:
    api = FakeAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [{"date": "20260213", "close": 100, "volume": 1}]
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    result = bot.run_once(now=datetime(2026, 2, 14, 8, 50))

    assert result["status"] == "PASS"
    assert result["reason"] == "HOLIDAY"
    assert api.order_calls == []


def test_bot_holiday_is_checked_once_per_day(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    class CountAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self.daily_bars_calls = 0

        def daily_bars(self, code: str, end: str, lookback: int) -> pd.DataFrame:
            self.daily_bars_calls += 1
            return super().daily_bars(code, end, lookback)

    api = CountAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [{"date": "20260213", "close": 100, "volume": 1}]
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]

    out1 = bot.run_once(now=datetime(2026, 2, 14, 8, 50))
    out2 = bot.run_once(now=datetime(2026, 2, 14, 9, 0))

    assert out1["status"] == "PASS"
    assert out1["reason"] == "HOLIDAY"
    assert out2["status"] == "PASS"
    assert out2["reason"] == "HOLIDAY"
    assert api.daily_bars_calls == 2
    assert bot.state.pass_reasons_today.get("HOLIDAY") == 2

    holiday_pass_msgs = [t for t in notifier.texts if t.startswith("[PASS] HOLIDAY")]
    assert len(holiday_pass_msgs) == 1


def test_bot_daily_max_loss_pass_notified_once_per_day(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]

    bot._pass("DAILY_MAX_LOSS", regime="RISK_ON")
    bot._pass("DAILY_MAX_LOSS", regime="RISK_ON")

    assert bot.state.pass_reasons_today.get("DAILY_MAX_LOSS") == 2
    daily_max_loss_msgs = [t for t in notifier.texts if t.startswith("[PASS] DAILY_MAX_LOSS")]
    assert len(daily_max_loss_msgs) == 1


def test_bot_risk_off_pass_notified_once_per_day(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]

    bot._pass("RISK_OFF", regime="RISK_OFF")
    bot._pass("RISK_OFF", regime="RISK_OFF")

    assert bot.state.pass_reasons_today.get("RISK_OFF") == 2
    risk_off_msgs = [t for t in notifier.texts if t.startswith("[PASS] RISK_OFF")]
    assert len(risk_off_msgs) == 1


def test_bot_candidate_notification_visible_in_risk_off(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]

    candidates = SimpleNamespace(
        popular=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_5d": 210_000_000_000,
                    "avg_value_20d": 205_000_000_000,
                }
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_5d": 210_000_000_000,
                    "avg_value_20d": 205_000_000_000,
                }
            ]
        )
    )

    now = datetime(2026, 2, 16, 9, 10)  # default entry window 안
    bot._maybe_notify_candidates(now, candidates, regime="RISK_OFF")
    bot._maybe_notify_candidates(now, candidates, regime="RISK_OFF")  # same window dedupe

    candidate_msgs = [t for t in notifier.texts if t.startswith("⚡ [Entry Window] [DAY] Scanned Symbols (RISK_OFF)")]
    assert len(candidate_msgs) == 1
    assert "관찰 전용" in candidate_msgs[0]
    assert "440650" in candidate_msgs[0]
    assert "005930" in candidate_msgs[0]


def test_bot_candidate_notification_prefers_ranked_display_candidates(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]

    candidates = SimpleNamespace(
        popular=pd.DataFrame(
            [
                {"code": "RAW001", "name": "원시후보", "avg_value_5d": 210_000_000_000},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "RAW001", "name": "원시후보", "avg_value_5d": 210_000_000_000},
            ]
        )
    )
    display_candidates = pd.DataFrame(
        [
            {"code": "TOP001", "name": "정제후보", "avg_value_5d": 180_000_000_000},
        ]
    )

    now = datetime(2026, 2, 16, 9, 10)
    bot._maybe_notify_candidates(
        now,
        candidates,
        regime="RISK_ON",
        display_candidates=display_candidates,
    )

    candidate_msgs = [t for t in notifier.texts if t.startswith("⚡ [Entry Window] [DAY] Scanned Symbols (RISK_ON)")]
    assert len(candidate_msgs) == 1
    assert "TOP001" in candidate_msgs[0]
    assert "RAW001" not in candidate_msgs[0]


def test_bot_candidate_notification_sends_day_and_swing_separately(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]

    candidates = SimpleNamespace(
        popular=pd.DataFrame(
            [
                {"code": "DAY001", "name": "단타후보", "avg_value_5d": 170_000_000_000},
            ]
        ),
        model=pd.DataFrame(
            [
                {"code": "SWG001", "name": "스윙후보", "avg_value_20d": 320_000_000_000},
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "DAY001", "name": "단타후보", "avg_value_5d": 170_000_000_000},
                {"code": "SWG001", "name": "스윙후보", "avg_value_20d": 320_000_000_000},
            ]
        ),
    )
    display_candidates = pd.DataFrame(
        [
            {"code": "DAY001", "name": "단타후보", "avg_value_5d": 170_000_000_000},
        ]
    )

    bot._maybe_notify_candidates(
        datetime(2026, 2, 16, 9, 10),
        candidates,
        regime="RISK_ON",
        display_candidates=display_candidates,
    )

    assert len(notifier.texts) == 2
    assert notifier.texts[0].startswith("📈 [Entry Window] [SWING] Scanned Symbols (RISK_ON)")
    assert "SWG001" in notifier.texts[0]
    assert notifier.texts[1].startswith("⚡ [Entry Window] [DAY] Scanned Symbols (RISK_ON)")
    assert "DAY001" in notifier.texts[1]


def test_bot_risk_off_parks_cash_in_bond_etf(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260323"
    api = FakeAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_000, "change_pct": 0.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
        risk_off_parking_cash_ratio=0.95,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 23, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 95, "order_type": "best", "price": None}
    ]
    assert bot.state.pass_reasons_today.get("RISK_OFF") == 1
    assert "440650" in bot.state.open_positions
    assert bot.state.open_positions["440650"].type == "P"
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650") for text in notifier.texts)


def test_bot_rebuys_risk_off_parking_after_stale_local_position_is_dropped(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260325"
    api = FakeAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_000, "change_pct": 0.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
        risk_off_parking_cash_ratio=0.95,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-23T10:44:00",
        entry_price=12_475.0,
        qty=72,
        highest_price=12_475.0,
        entry_date="20260323",
    )
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 95, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["440650"].qty == 95
    assert any(text.startswith("[STATE_SYNC][DROP] 440650") for text in notifier.texts)
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650") for text in notifier.texts)


def test_bot_risk_off_failed_parking_order_does_not_emit_fake_entry(tmp_path) -> None:
    class RejectingAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": False, "msg": "주문가능금액을 초과 했습니다"}

    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260325"
    api = RejectingAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_000, "change_pct": 0.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
        risk_off_parking_cash_ratio=0.95,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 95, "order_type": "best", "price": None},
        {"side": "BUY", "code": "440650", "qty": 94, "order_type": "best", "price": None},
    ]
    assert "440650" not in bot.state.open_positions
    assert not any(text.startswith("[ENTRY][P][RISK_OFF] 440650") for text in notifier.texts)


def test_bot_risk_off_reduces_qty_after_insufficient_cash_rejection(tmp_path) -> None:
    class TightCashAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            if side == "BUY" and code == "440650" and qty >= 73:
                return {"success": False, "msg": "주문가능금액을 초과 했습니다"}
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": price or self.quote(code).get("price", 0),
            }

    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260325"
    api = TightCashAPI()
    api._cash_available = 954_514
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 12_365, "change_pct": 0.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
        risk_off_parking_cash_ratio=0.95,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 73, "order_type": "best", "price": None},
        {"side": "BUY", "code": "440650", "qty": 72, "order_type": "best", "price": None},
    ]
    assert bot.state.open_positions["440650"].qty == 72
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650 qty=72") for text in notifier.texts)


def test_bot_risk_off_uses_broker_buyable_amount_before_parking_order(tmp_path) -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "440650"
            assert order_type == "best"
            assert price is None or price > 0
            return {
                "ord_psbl_cash": 900_000,
                "nrcvb_buy_amt": 900_000,
                "nrcvb_buy_qty": 68,
                "max_buy_qty": 72,
                "psbl_qty_calc_unpr": 12_500,
            }

    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260325"
    api = BuyableAPI()
    api._cash_available = 2_000_000
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 12_365, "change_pct": 0.1}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
        risk_off_parking_cash_ratio=0.95,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 25, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 68, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["440650"].qty == 68
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650 qty=68") for text in notifier.texts)


def test_bot_risk_off_tops_up_existing_parking_position(tmp_path) -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "440650"
            assert order_type == "best"
            assert price is None or price > 0
            return {
                "ord_psbl_cash": 100_000,
                "nrcvb_buy_amt": 100_000,
                "nrcvb_buy_qty": 9,
                "max_buy_qty": 9,
                "psbl_qty_calc_unpr": 10_000,
            }

    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260326"
    api = BuyableAPI()
    api._cash_available = 500_000
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 100, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_000, "change_pct": 0.1}
    api._positions = [{"code": "440650", "qty": 50, "avg_price": 10_000.0}]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
        risk_off_parking_cash_ratio=0.95,
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-26T09:00:00",
        entry_price=10_000.0,
        qty=50,
        highest_price=10_000.0,
        entry_date=asof,
    )
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_OFF", asof)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 26, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert api.order_calls == [
        {"side": "BUY", "code": "440650", "qty": 9, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["440650"].qty == 59
    assert any(text.startswith("[ENTRY][P][RISK_OFF] 440650 qty=9") for text in notifier.texts)


def test_exit_position_caps_sell_qty_by_broker_sellable_amount() -> None:
    class SellableAPI(FakeAPI):
        def sell_order_capacity(self, code: str) -> dict:
            assert code == "440650"
            return {
                "ord_psbl_qty": 30,
                "hldg_qty": 50,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": price or self.quote(code).get("price", 0),
            }

    api = SellableAPI()
    api._quotes["440650"] = {"price": 12_500, "change_pct": 0.1}
    state = new_state("20260325")
    state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-25T10:00:00",
        entry_price=12_000.0,
        qty=50,
        highest_price=12_500.0,
        entry_date="20260325",
        bars_held=0,
    )

    result = exit_position(
        api,
        state,
        code="440650",
        reason="RISK_ON",
        now=datetime(2026, 3, 25, 10, 30),
    )

    assert result is not None
    assert result.qty == 30
    assert api.order_calls == [
        {"side": "SELL", "code": "440650", "qty": 30, "order_type": "MKT", "price": None}
    ]
    assert "440650" in state.open_positions
    assert state.open_positions["440650"].qty == 20
    assert state.realized_pnl_today == 15_000.0
    assert state.realized_pnl_total == 15_000.0


def test_monitor_positions_excludes_day_stoploss_symbol_after_third_loss(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["011930"] = {"price": 9_800, "change_pct": -2.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.day_stoploss_fail_counts["011930"] = 2
    bot.state.open_positions["011930"] = PositionState(
        type="T",
        entry_time="2026-04-07T09:05:00",
        entry_price=10_000.0,
        qty=10,
        highest_price=10_000.0,
        entry_date="20260407",
    )

    now = datetime(2026, 4, 7, 9, 30)
    bot.monitor_positions(now=now)

    assert "011930" not in bot.state.open_positions
    assert get_day_stoploss_fail_count(bot.state, "011930") == 3
    assert "011930" in bot.state.day_stoploss_excluded_codes
    assert "011930" in get_day_stoploss_excluded_codes(bot.state)


def test_monitor_positions_tracks_day_stoploss_count_before_exclusion(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["011930"] = {"price": 9_800, "change_pct": -2.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.day_stoploss_fail_counts["011930"] = 1
    bot.state.open_positions["011930"] = PositionState(
        type="T",
        entry_time="2026-04-07T09:05:00",
        entry_price=10_000.0,
        qty=10,
        highest_price=10_000.0,
        entry_date="20260407",
    )

    now = datetime(2026, 4, 7, 9, 30)
    bot.monitor_positions(now=now)

    assert "011930" not in bot.state.open_positions
    assert get_day_stoploss_fail_count(bot.state, "011930") == 2
    assert "011930" not in bot.state.day_stoploss_excluded_codes
    assert "011930" not in get_day_stoploss_excluded_codes(bot.state)


def test_monitor_positions_temporarily_excludes_swing_time_exit_symbol(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005930"] = {"price": 10_000, "change_pct": 0.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-07T09:05:00",
        entry_price=10_000.0,
        qty=10,
        highest_price=10_000.0,
        entry_date="20260324",
        bars_held=10,
    )

    now = datetime(2026, 4, 7, 10, 30)
    bot.monitor_positions(now=now)

    assert "005930" not in bot.state.open_positions
    assert "005930" in bot.state.swing_time_excluded_codes
    assert "005930" in get_swing_time_excluded_codes(bot.state)


def test_bot_skips_day_stoploss_excluded_symbol_on_next_daytrade_entry(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 1_000, "change_pct": 8.0}
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    for _ in range(cfg.day_stoploss_exclude_after_losses):
        record_day_stoploss_failure(
            bot.state,
            code="011930",
            exclude_after_losses=cfg.day_stoploss_exclude_after_losses,
        )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000", "close": 1000, "change_pct": "8.0", "is_etf": False},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "10000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000"},
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "10000000000"},
            ]
        ),
        quote_codes=["011930", "005930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "best", "price": None}
    ]
    assert "011930" not in bot.state.open_positions
    assert "005930" in bot.state.open_positions


def test_bot_allows_daytrade_reentry_before_day_stoploss_threshold(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.day_stoploss_fail_counts["011930"] = cfg.day_stoploss_exclude_after_losses - 1

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["011930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "011930", "qty": 4, "order_type": "best", "price": None}
    ]
    assert "011930" in bot.state.open_positions
    assert bot.state.open_positions["011930"].type == "T"


def test_bot_skips_swing_time_excluded_symbol_on_next_swing_entry(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 50_000, "change_pct": 1.5}
    api._quotes["000660"] = {"price": 50_000, "change_pct": 1.4}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.swing_time_excluded_codes.add("011930")

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "011930",
                    "name": "신성이엔지",
                    "avg_value_20d": "900000000000",
                    "ma20": 48_000,
                    "ma60": 45_000,
                    "close": 50_000,
                    "change_pct": "1.5",
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "000660",
                    "name": "SK하이닉스",
                    "avg_value_20d": "800000000000",
                    "ma20": 48_000,
                    "ma60": 45_000,
                    "close": 50_000,
                    "change_pct": "1.4",
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_20d": "900000000000"},
                {"code": "000660", "name": "SK하이닉스", "avg_value_20d": "800000000000"},
            ]
        ),
        quote_codes=["011930", "000660"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "000660", "qty": 16, "order_type": "best", "price": None}
    ]
    assert "011930" not in bot.state.open_positions
    assert "000660" in bot.state.open_positions


def test_bot_allows_swing_entry_for_day_stoploss_excluded_symbol(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["011930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    for _ in range(cfg.day_stoploss_exclude_after_losses):
        record_day_stoploss_failure(
            bot.state,
            code="011930",
            exclude_after_losses=cfg.day_stoploss_exclude_after_losses,
        )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "011930",
                    "name": "신성이엔지",
                    "avg_value_20d": "800000000000",
                    "ma20": 48_000,
                    "ma60": 45_000,
                    "close": 50_000,
                    "change_pct": "1.5",
                    "is_etf": False,
                    "trend_tier": "strict",
                }
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "011930", "name": "신성이엔지", "avg_value_20d": "800000000000"},
            ]
        ),
        quote_codes=["011930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == [
        {"side": "BUY", "code": "011930", "qty": 16, "order_type": "best", "price": None}
    ]
    assert "011930" in bot.state.open_positions
    assert bot.state.open_positions["011930"].type == "S"


def test_day_entry_uses_strategy_cap_not_remaining_cash(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 250_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-04-08T09:05:00",
        entry_price=100_000.0,
        qty=8,
        highest_price=100_000.0,
        entry_date="20260408",
        bars_held=2,
    )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["005930"].qty == 4


def test_day_entry_adds_realized_profit_buffer_on_top_of_strategy_cap(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 260_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
        use_realized_profit_buffer=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.realized_pnl_total = 50_000.0

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 5, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["005930"].qty == 5


def test_day_entry_uses_account_basis_buffer_without_unrealized_gain(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 250_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}
    api._positions = [
        {
            "code": "SWING01",
            "qty": 8,
            "avg_price": 100_000.0,
            "current_price": 110_000,
            "pnl": 80_000,
        }
    ]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
        use_realized_profit_buffer=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 5, "order_type": "best", "price": None}
    ]
    assert bot.state.open_positions["005930"].qty == 5


def test_enter_position_returns_sizing_metadata() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "005930"
            assert order_type == "best"
            assert price == 50_000
            return {
                "ord_psbl_cash": 900_000,
                "nrcvb_buy_amt": 900_000,
                "nrcvb_buy_qty": 14,
                "max_buy_qty": 14,
                "psbl_qty_calc_unpr": 50_000,
            }

    api = BuyableAPI()
    api._cash_available = 1_000_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.0}
    state = new_state("20260408")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="S",
        code="005930",
        cash_ratio=0.8,
        asof_date="20260408",
        now=datetime(2026, 4, 8, 9, 10),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 14
    assert result.sizing == {
        "cash_available_snapshot": 1_000_000,
        "sizing_cash": 900_000,
        "quote_price": 50_000.0,
        "sizing_price": 50_000.0,
        "budget_cash": 720_000,
        "max_qty": 14,
        "requested_qty": 14,
        "cash_ratio": 0.8,
        "order_type": "best",
    }


def test_enter_position_best_order_uses_quote_price_before_retrying_down() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "050890"
            assert order_type == "best"
            assert price == 17_430
            return {
                "ord_psbl_cash": 374_960,
                "nrcvb_buy_amt": 374_960,
                "nrcvb_buy_qty": 17,
                "max_buy_qty": 17,
                "psbl_qty_calc_unpr": 21_900,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            if qty >= 11:
                return {"success": False, "msg": "주문가능금액을 초과 했습니다"}
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": self.quote(code).get("price", 0),
            }

    api = BuyableAPI()
    api._cash_available = 378_245
    api._quotes["050890"] = {"price": 17_430, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="050890",
        cash_ratio=1.0,
        budget_cash_cap=200_000,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 10
    assert api.order_calls == [
        {"side": "BUY", "code": "050890", "qty": 11, "order_type": "best", "price": None},
        {"side": "BUY", "code": "050890", "qty": 10, "order_type": "best", "price": None},
    ]
    assert result.sizing == {
        "cash_available_snapshot": 378_245,
        "sizing_cash": 374_960,
        "quote_price": 17_430.0,
        "sizing_price": 17_430.0,
        "budget_cash": 200_000,
        "max_qty": 17,
        "requested_qty": 10,
        "cash_ratio": 1.0,
        "order_type": "best",
    }


def test_enter_position_does_not_book_fill_from_order_acceptance_only() -> None:
    class PendingOnlyAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": True, "order_id": f"{side}-{code}", "msg": "주문 접수"}

    api = PendingOnlyAPI()
    api._cash_available = 500_000
    api._quotes["005930"] = {"price": 100_000, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="S",
        code="005930",
        cash_ratio=0.5,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="MKT",
    )

    assert result is None
    assert "005930" not in state.open_positions
    assert state.swing_entries_today == 0


def test_exit_position_does_not_book_fill_from_order_acceptance_only() -> None:
    class PendingOnlyAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": True, "order_id": f"{side}-{code}", "msg": "주문 접수"}

    api = PendingOnlyAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.0}
    api._positions = [{"code": "005930", "qty": 10, "avg_price": 100_000.0}]
    state = new_state("20260415")
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-14T09:00:00",
        entry_price=100_000.0,
        qty=10,
        highest_price=105_000.0,
        entry_date="20260414",
    )

    result = exit_position(
        api,
        state,
        code="005930",
        reason="TP",
        now=datetime(2026, 4, 15, 10, 0),
    )

    assert result is None
    assert state.open_positions["005930"].qty == 10
    assert state.realized_pnl_today == 0.0


def test_handle_open_orders_only_cancels_stale_orders() -> None:
    class OpenOrderAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._open_orders = [
                {"order_id": "old-1", "order_time": "090000", "remaining_qty": 3},
                {"order_id": "recent-1", "order_time": "090045", "remaining_qty": 2},
                {"order_id": "filled-1", "order_time": "085900", "remaining_qty": 0, "status": "FILLED"},
                {"order_id": "unknown-1", "remaining_qty": 1},
            ]
            self.cancelled_ids: list[str] = []

        def open_orders(self) -> list[dict]:
            return list(self._open_orders)

        def cancel_order(self, order_id: str) -> dict:
            self.cancelled_ids.append(order_id)
            return {"order_id": order_id, "status": "cancelled"}

    from backend.services.trading_engine.execution import handle_open_orders

    api = OpenOrderAPI()
    result = handle_open_orders(
        api,
        timeout_sec=30,
        now=datetime(2026, 4, 15, 9, 1, 0),
    )

    assert api.cancelled_ids == ["old-1"]
    assert result == {"cancelled": 1, "skipped_recent": 1, "skipped_unknown_time": 1}


def test_reconcile_state_updates_qty_and_avg_price_from_broker_snapshot() -> None:
    from backend.services.trading_engine.position_helpers import reconcile_state_with_broker_positions

    api = FakeAPI()
    api._positions = [{"code": "005930", "qty": 3, "avg_price": 98_000.0}]
    state = new_state("20260415")
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-14T09:00:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=105_000.0,
        entry_date="20260414",
    )
    journal_rows: list[tuple[str, dict]] = []
    notifications: list[str] = []

    reconcile_state_with_broker_positions(
        api,
        state,
        trade_date="20260415",
        journal=lambda event, **fields: journal_rows.append((event, fields)),
        notify_text=notifications.append,
    )

    pos = state.open_positions["005930"]
    assert pos.qty == 3
    assert pos.entry_price == 98_000.0
    assert journal_rows[0][0] == "STATE_RECONCILE_UPDATE"
    assert notifications == ["[STATE_SYNC][UPDATE] 005930 qty=5->3 avg=100000->98000"]


def test_save_state_roundtrip_uses_atomic_replace(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state = new_state("20260415")
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-04-14T09:00:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=105_000.0,
        entry_date="20260414",
    )

    save_state(str(state_path), state)
    loaded = load_state(str(state_path))

    assert loaded.trade_date == "20260415"
    assert loaded.open_positions["005930"].qty == 5
    assert state_path.read_text(encoding="utf-8").endswith("\n")


def test_bot_risk_on_exits_existing_risk_off_parking(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260324"
    api = FakeAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 101, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_100, "change_pct": 0.5}
    api._positions = [{"code": "440650", "qty": 50, "avg_price": 10_000.0}]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-23T10:05:00",
        entry_price=10_000.0,
        qty=50,
        highest_price=10_000.0,
        entry_date="20260323",
    )
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 24, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_ON"
    assert api.order_calls[0] == {
        "side": "SELL",
        "code": "440650",
        "qty": 50,
        "order_type": "MKT",
        "price": None,
    }
    assert "440650" not in bot.state.open_positions
    assert any(text.startswith("[EXIT][P][RISK_ON] 440650") for text in notifier.texts)


def test_bot_risk_on_failed_parking_exit_keeps_position(tmp_path) -> None:
    class RejectingAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": False, "msg": "매도주문이 거부되었습니다"}

    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    asof = "20260324"
    api = RejectingAPI()
    api._bars[("069500", asof)] = pd.DataFrame(
        [{"date": asof, "close": 101, "volume": 1}]
    )
    api._quotes["440650"] = {"price": 10_100, "change_pct": 0.5}
    api._positions = [{"code": "440650", "qty": 50, "avg_price": 10_000.0}]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        risk_off_parking_enabled=True,
        risk_off_parking_code="440650",
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.open_positions["440650"] = PositionState(
        type="P",
        entry_time="2026-03-23T10:05:00",
        entry_price=10_000.0,
        qty=50,
        highest_price=10_000.0,
        entry_date="20260323",
    )
    empty_candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
        with patch("backend.services.trading_engine.bot.build_candidates", return_value=empty_candidates):
            out = bot.run_once(now=datetime(2026, 3, 24, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_ON"
    assert api.order_calls == [
        {"side": "SELL", "code": "440650", "qty": 50, "order_type": "MKT", "price": None}
    ]
    assert "440650" in bot.state.open_positions
    assert not any(text.startswith("[EXIT][P][RISK_ON] 440650") for text in notifier.texts)


def test_swing_can_retry_in_second_window_after_morning_no_pick(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    api._quotes["005930"] = {"price": 100_000, "change_pct": 1.2}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"

    candidates = SimpleNamespace(
        model=pd.DataFrame([{"code": "005930", "name": "삼성전자"}]),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.pick_swing", return_value=None):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={},
        )

    assert api.order_calls == []
    assert bot.state.swing_entries_today == 0
    assert bot.state.pass_reasons_today.get("NO_SWING_PICK") == 1
    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[SWING][SKIP]")]
    assert len(swing_skip_msgs) == 1
    assert "후보를 끝까지 못 좁혀서" in swing_skip_msgs[0]
    assert "13:00-13:20 창에서 다시 볼게." in swing_skip_msgs[0]

    with patch("backend.services.trading_engine.bot.pick_swing", return_value="005930"):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
        )

    assert bot.state.swing_entries_today == 1
    assert "005930" in bot.state.open_positions
    assert api.order_calls == [
            {
                "side": "BUY",
                "code": "005930",
                "qty": 8,
                "order_type": "best",
                "price": None,
            }
        ]


def test_swing_no_candidate_notified_once_per_window(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"

    empty_candidates = SimpleNamespace(
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
    )

    bot._try_enter_swing(
        now=datetime(2026, 2, 16, 9, 10),
        regime="RISK_ON",
        candidates=empty_candidates,
        quotes={},
    )
    bot._try_enter_swing(
        now=datetime(2026, 2, 16, 9, 14),
        regime="RISK_ON",
        candidates=empty_candidates,
        quotes={},
    )

    assert api.order_calls == []
    assert bot.state.pass_reasons_today.get("NO_CANDIDATE") == 2
    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[SWING][SKIP]")]
    assert len(swing_skip_msgs) == 1
    assert "스윙 후보가 안 보여서" in swing_skip_msgs[0]
    assert "13:00-13:20 창에서 다시 볼게." in swing_skip_msgs[0]


def test_swing_skip_notification_suppressed_when_swing_position_already_open(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"
    bot.state.open_positions["379800"] = PositionState(
        type="S",
        entry_time="2026-02-16T13:00:00",
        entry_price=23_475.0,
        qty=33,
        highest_price=23_475.0,
        entry_date="20260216",
    )

    empty_candidates = SimpleNamespace(
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
    )

    bot._try_enter_swing(
        now=datetime(2026, 2, 16, 13, 8),
        regime="RISK_ON",
        candidates=empty_candidates,
        quotes={},
    )

    assert bot.state.pass_reasons_today.get("NO_CANDIDATE") == 1
    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[SWING][SKIP]")]
    assert swing_skip_msgs == []


def test_swing_skip_message_uses_local_llm_rewrite_when_available(tmp_path) -> None:
    class SpyNotifier:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.files: list[tuple[str, str | None]] = []

        def enqueue_text(self, text: str) -> None:
            self.texts.append(text)

        def enqueue_file(self, path: str, caption: str | None = None) -> None:
            self.files.append((path, caption))

        def flush(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

        def close(self, timeout_sec: float = 2.0) -> None:
            del timeout_sec

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "스윙 후보가 안 보여서 이번 창은 쉬어갔어. 13시에 다시 볼게!"
                        }
                    }
                ]
            }

    api = FakeAPI()
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = SpyNotifier()
    bot = HybridTradingBot(api, config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260216"

    empty_candidates = SimpleNamespace(
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.candidate_notifications.load_prompt", return_value="test prompt"):
        with patch.dict(
            "os.environ",
            {
                "LLM_BASE_URL": "http://openvino-server:8082",
                "LLM_TIMEOUT": "4",
                "LLM_REMOTE_DEFAULT_MODEL": "Josiefied-Qwen3-8B-int8",
            },
            clear=False,
        ):
            with patch("backend.services.trading_engine.candidate_notifications.requests.post", return_value=FakeResponse()) as post_mock:
                bot._try_enter_swing(
                    now=datetime(2026, 2, 16, 9, 10),
                    regime="RISK_ON",
                    candidates=empty_candidates,
                    quotes={},
                )

    swing_skip_msgs = [t for t in notifier.texts if t.startswith("[SWING][SKIP]")]
    assert swing_skip_msgs == ["[SWING][SKIP] 스윙 후보가 안 보여서 이번 창은 쉬어갔어. 13시에 다시 볼게!"]
    assert post_mock.call_count == 1
    request_payload = post_mock.call_args.kwargs["json"]
    assert request_payload["model"] == "Josiefied-Qwen3-8B-int8"
    assert request_payload["chat_template_kwargs"]["enable_thinking"] is False


def test_swing_lunch_retry_still_respects_existing_position_limit() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")
    state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:10:00",
        entry_price=100_000.0,
        qty=7,
        highest_price=100_000.0,
        entry_date="20260216",
    )

    ok, reason = can_enter(
        "S",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    assert ok is False
    assert reason == "MAX_SWING_POSITIONS"


def test_swing_hold_skips_rebuy_when_same_symbol_is_already_profitable(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.2}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    bot.state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:10:00",
        entry_price=100_000.0,
        qty=7,
        highest_price=105_000.0,
        entry_date="20260216",
    )

    candidates = SimpleNamespace(
        model=pd.DataFrame([{"code": "005930", "name": "삼성전자"}]),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.pick_swing", return_value="005930"):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
        )

    assert api.order_calls == []
    assert bot.state.pass_reasons_today == {}
    assert bot.state.open_positions["005930"].qty == 7
    assert abs(float(bot.state.open_positions["005930"].locked_profit_pct or 0.0) - 0.05) < 1e-9


def test_locked_profit_position_exits_immediately_after_profit_floor_break(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.2}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_take_profit_mode="trailing",
        swing_trail_start=0.50,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    bot.state.open_positions["005930"] = PositionState(
        type="S",
        entry_time="2026-02-16T09:10:00",
        entry_price=100_000.0,
        qty=7,
        highest_price=105_000.0,
        entry_date="20260216",
    )

    candidates = SimpleNamespace(
        model=pd.DataFrame([{"code": "005930", "name": "삼성전자"}]),
        etf=pd.DataFrame(),
    )

    with patch("backend.services.trading_engine.bot.pick_swing", return_value="005930"):
        bot._try_enter_swing(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
        )

    api._quotes["005930"] = {"price": 104_000, "change_pct": 0.8}
    bot.monitor_positions(now=datetime(2026, 2, 16, 13, 14))

    assert any(call["side"] == "SELL" and call["code"] == "005930" for call in api.order_calls)
    assert "005930" not in bot.state.open_positions


def test_day_position_arms_profit_lock_and_exits_on_retrace() -> None:
    cfg = TradeEngineConfig(
        day_lock_profit_trigger_pct=0.009,
        day_lock_profit_floor_pct=0.002,
        day_lock_retrace_gap_pct=0.006,
    )
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=101_500.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=101_500.0,
        now=datetime(2026, 2, 16, 9, 20),
        config=cfg,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.015
    assert abs(float(position.locked_profit_pct or 0.0) - 0.009) < 1e-9

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=100_800.0,
        now=datetime(2026, 2, 16, 9, 24),
        config=cfg,
    )

    assert exit_now is True
    assert reason == "LOCK"
    assert round(pnl_pct, 4) == 0.008


def test_day_position_volatility_aware_lock_allows_early_pullback() -> None:
    cfg = TradeEngineConfig(
        day_lock_profit_trigger_pct=0.009,
        day_lock_profit_floor_pct=0.005,
        day_lock_retrace_gap_pct=0.006,
        day_take_profit_pct=0.050,
    )
    position = PositionState(
        type="T",
        entry_time="2026-02-16T09:05:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=101_800.0,
        entry_date="20260216",
    )

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=101_800.0,
        now=datetime(2026, 2, 16, 9, 12),
        config=cfg,
        day_lock_retrace_gap_pct_override=0.013,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.018
    assert abs(float(position.locked_profit_pct or 0.0) - 0.005) < 1e-9

    exit_now, reason, pnl_pct = should_exit_position(
        position,
        quote_price=100_900.0,
        now=datetime(2026, 2, 16, 9, 16),
        config=cfg,
        day_lock_retrace_gap_pct_override=0.013,
    )

    assert exit_now is False
    assert reason == ""
    assert round(pnl_pct, 4) == 0.009


def test_day_hold_match_does_not_tighten_lock_to_full_profit(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["005880"] = {"price": 101_800, "change_pct": 1.8}
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = "20260216"
    bot.state.open_positions["005880"] = PositionState(
        type="T",
        entry_time="2026-02-16T09:08:00",
        entry_price=100_000.0,
        qty=5,
        highest_price=100_000.0,
        entry_date="20260216",
        locked_profit_pct=0.005,
    )

    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame([{"code": "005880"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["005880"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 12),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005880": api.quote("005880")},
            news_signal=None,
        )

    assert api.order_calls == []
    assert "005880" in bot.state.open_positions
    assert abs(float(bot.state.open_positions["005880"].locked_profit_pct or 0.0) - 0.005) < 1e-9
    assert abs(float(bot.state.open_positions["005880"].highest_price or 0.0) - 101_800.0) < 1e-9


def test_day_entry_window_advances_to_afternoon_after_morning_fill() -> None:
    cfg = TradeEngineConfig()
    state = new_state("20260216")

    ok_morning, reason_morning = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )
    ok_lunch, reason_lunch = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    state.day_entries_today = 1
    ok_second_morning, reason_second_morning = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 9, 10),
        config=cfg,
    )
    ok_afternoon, reason_afternoon = can_enter(
        "T",
        state,
        regime="RISK_ON",
        candidates_count=1,
        now=datetime(2026, 2, 16, 13, 10),
        config=cfg,
    )

    assert ok_morning is True
    assert reason_morning == "OK"
    assert ok_lunch is False
    assert reason_lunch == "ENTRY_WINDOW_CLOSED"
    assert ok_second_morning is False
    assert reason_second_morning == "ENTRY_WINDOW_CLOSED"
    assert ok_afternoon is True
    assert reason_afternoon == "OK"


def test_rank_daytrade_codes_prefers_near_high_strength_over_faded_liquidity() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(
            [
                {
                    "code": "FADE01",
                    "name": "Fade Corp",
                    "avg_value_5d": 500_000_000_000,
                    "close": 101.0,
                    "change_pct": 1.0,
                    "is_etf": False,
                },
                {
                    "code": "LEAD01",
                    "name": "Leader Corp",
                    "avg_value_5d": 60_000_000_000,
                    "close": 106.0,
                    "change_pct": 3.0,
                    "is_etf": False,
                },
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["FADE01", "LEAD01"],
    )
    quotes = {
        "FADE01": {
            "price": 101.0,
            "open": 101.0,
            "high": 106.0,
            "low": 100.0,
            "change_pct": 1.0,
        },
        "LEAD01": {
            "price": 106.0,
            "open": 103.0,
            "high": 107.0,
            "low": 102.0,
            "change_pct": 3.0,
        },
    }

    ranked = rank_daytrade_codes(candidates, quotes, cfg)

    assert ranked[:2] == ["LEAD01", "FADE01"]


def test_pick_swing_prefers_sector_etf_on_theme_day() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=True)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": 1_800_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 110.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "000660",
                    "name": "SK하이닉스",
                    "avg_value_20d": 1_200_000_000_000,
                    "ma20": 95.0,
                    "ma60": 90.0,
                    "close": 103.0,
                    "change_pct": 3.2,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(
            [
                {
                    "code": "ETF001",
                    "name": "KODEX 반도체",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 98.0,
                    "ma60": 93.0,
                    "close": 108.0,
                    "change_pct": 2.8,
                    "is_etf": True,
                },
                {
                    "code": "ETF002",
                    "name": "TIGER 반도체TOP10",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 99.0,
                    "ma60": 94.0,
                    "close": 109.0,
                    "change_pct": 3.1,
                    "is_etf": True,
                }
            ]
        ),
        merged=pd.DataFrame(),
        quote_codes=["005930", "000660", "ETF001", "ETF002"],
    )
    quotes = {
        "005930": {"price": 110.0, "change_pct": 4.0},
        "000660": {"price": 103.0, "change_pct": 3.2},
        "ETF001": {"price": 108.0, "change_pct": 2.8},
        "ETF002": {"price": 109.0, "change_pct": 3.1},
    }
    news_signal = NewsSentimentSignal(
        market_score=0.3,
        sector_scores={"semiconductor": 0.75},
        sector_keywords={"semiconductor": ("반도체", "삼성전자", "sk하이닉스")},
        article_count=50,
    )

    picked = pick_swing(candidates, quotes, cfg, news_signal=news_signal)

    assert picked == "ETF001"


def test_pick_swing_keeps_stock_when_theme_breadth_is_not_met() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=True)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": 1_800_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 110.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(
            [
                {
                    "code": "ETF001",
                    "name": "KODEX 반도체",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 98.0,
                    "ma60": 93.0,
                    "close": 108.0,
                    "change_pct": 2.8,
                    "is_etf": True,
                }
            ]
        ),
        merged=pd.DataFrame(),
        quote_codes=["005930", "ETF001"],
    )
    quotes = {
        "005930": {"price": 110.0, "change_pct": 4.0},
        "ETF001": {"price": 108.0, "change_pct": 2.8},
    }
    news_signal = NewsSentimentSignal(
        market_score=0.3,
        sector_scores={"semiconductor": 0.75},
        sector_keywords={"semiconductor": ("반도체", "삼성전자", "sk하이닉스")},
        article_count=50,
    )

    picked = pick_swing(candidates, quotes, cfg, news_signal=news_signal)

    assert picked == "005930"


def test_pick_swing_prefers_stock_holding_near_high_over_faded_large_cap() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "FADE01",
                    "name": "Fade LargeCap",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 108.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "LEAD01",
                    "name": "Leader LargeCap",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100.0,
                    "ma60": 96.0,
                    "close": 109.0,
                    "change_pct": 3.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["FADE01", "LEAD01"],
    )
    quotes = {
        "FADE01": {
            "price": 108.0,
            "open": 112.0,
            "high": 116.0,
            "low": 107.0,
            "change_pct": 4.0,
        },
        "LEAD01": {
            "price": 109.0,
            "open": 106.0,
            "high": 110.0,
            "low": 105.0,
            "change_pct": 3.5,
        },
    }

    picked = pick_swing(candidates, quotes, cfg, news_signal=None)

    assert picked == "LEAD01"


def test_day_entry_falls_back_to_next_affordable_candidate(tmp_path) -> None:
    api = FakeAPI()
    api._quotes["EXPENSIVE"] = {"price": 300_000, "change_pct": 6.0}
    api._quotes["AFFORD01"] = {"price": 10_000, "change_pct": 5.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
    )
    bot = HybridTradingBot(api, config=cfg)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame([{"code": "EXPENSIVE"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["EXPENSIVE", "AFFORD01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "AFFORD01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "AFFORD01", "qty": 20, "order_type": "best", "price": None}
    ]


def test_day_entry_reopens_in_afternoon_after_morning_round_trip(tmp_path) -> None:
    asof = "20260216"
    api = FakeAPI()
    api._quotes["MORN01"] = {"price": 10_000, "change_pct": 4.0}
    api._quotes["AFTER01"] = {"price": 10_000, "change_pct": 3.0}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "MORN01"}, {"code": "AFTER01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["MORN01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    first_exit = exit_position(
        api,
        bot.state,
        code="MORN01",
        reason="TP",
        now=datetime(2026, 2, 16, 9, 35),
        config=cfg,
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["AFTER01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 13, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert first_exit is not None
    assert bot.state.day_entries_today == 2
    assert "MORN01" not in bot.state.open_positions
    assert "AFTER01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "MORN01", "qty": 20, "order_type": "best", "price": None},
        {"side": "SELL", "code": "MORN01", "qty": 20, "order_type": "MKT", "price": None},
        {"side": "BUY", "code": "AFTER01", "qty": 20, "order_type": "best", "price": None},
    ]


def test_day_entry_skips_fading_intraday_candidate_and_uses_next_symbol(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["FADE01"] = {"price": 10_000, "change_pct": 2.0}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.4}
    api._intraday[("FADE01", asof)] = _make_intraday_bars(asof, [100.0, 102.0, 100.8])
    api._intraday[("KEEP01", asof)] = _make_intraday_bars(asof, [100.0, 100.3, 100.7])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "FADE01"}, {"code": "KEEP01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["FADE01", "KEEP01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "KEEP01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "KEEP01", "qty": 20, "order_type": "best", "price": None}
    ]


def test_day_entry_skips_candidate_when_intraday_fetch_fails(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            if code == "FAIL01":
                raise RuntimeError("transient broker error")
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["FAIL01"] = {"price": 10_000, "change_pct": 2.4}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.4}
    api._intraday[("KEEP01", asof)] = _make_intraday_bars(asof, [100.0, 100.3, 100.7])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "FAIL01"}, {"code": "KEEP01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["FAIL01", "KEEP01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "FAIL01" not in bot.state.open_positions
    assert "KEEP01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "KEEP01", "qty": 20, "order_type": "best", "price": None}
    ]


def test_day_entry_skips_candidate_when_intraday_data_is_missing(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["EMPTY01"] = {"price": 10_000, "change_pct": 2.1}
    api._quotes["KEEP01"] = {"price": 10_000, "change_pct": 1.4}
    api._intraday[("KEEP01", asof)] = _make_intraday_bars(asof, [100.0, 100.3, 100.7])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "EMPTY01"}, {"code": "KEEP01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["EMPTY01", "KEEP01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "EMPTY01" not in bot.state.open_positions
    assert "KEEP01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "KEEP01", "qty": 20, "order_type": "best", "price": None}
    ]


def test_day_entry_accepts_tight_base_intraday_candidate(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260216"
    api = IntradayAPI()
    api._quotes["BASE01"] = {"price": 10_000, "change_pct": 1.8}
    api._quotes["NEXT01"] = {"price": 10_000, "change_pct": 1.2}
    api._intraday[("BASE01", asof)] = _make_intraday_bars(
        asof,
        [100.0, 100.12, 100.18],
        last_change_pct=1.8,
    )
    api._intraday[("NEXT01", asof)] = _make_intraday_bars(
        asof,
        [100.0, 100.3, 100.7],
        last_change_pct=1.2,
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        day_cash_ratio=0.20,
        day_use_intraday_confirmation=True,
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame([{"code": "BASE01"}, {"code": "NEXT01"}]),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=[],
    )

    with patch(
        "backend.services.trading_engine.bot.rank_daytrade_codes",
        return_value=["BASE01", "NEXT01"],
    ):
        bot._try_enter_day(
            now=datetime(2026, 2, 16, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes=api._quotes,
            news_signal=None,
        )

    assert bot.state.day_entries_today == 1
    assert "BASE01" in bot.state.open_positions
    assert api.order_calls == [
        {"side": "BUY", "code": "BASE01", "qty": 20, "order_type": "best", "price": None}
    ]


def test_bot_holds_profitable_broker_position_when_same_symbol_is_picked(tmp_path) -> None:
    asof = "20260408"
    api = FakeAPI()
    api._quotes["005930"] = {"price": 105_000, "change_pct": 1.5}
    api._positions = [
        {"code": "005930", "qty": 3, "avg_price": 100_000.0, "current_price": 105_000, "pnl": 15_000}
    ]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": "800000000000",
                    "ma20": 102_000,
                    "ma60": 99_000,
                    "close": 105_000,
                    "change_pct": "1.5",
                    "is_etf": False,
                    "trend_tier": "strict",
                }
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_20d": "800000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.is_trading_day", return_value=True):
        with patch("backend.services.trading_engine.bot.get_regime", return_value=("RISK_ON", None)):
            with patch("backend.services.trading_engine.bot.build_candidates", return_value=candidates):
                with patch("backend.services.trading_engine.bot.build_news_sentiment_signal", return_value=None):
                    out = bot.run_once(now=datetime(2026, 4, 8, 9, 10))

    assert out["status"] == "OK"
    assert api.order_calls == []
    assert "005930" in bot.state.open_positions
    assert bot.state.open_positions["005930"].type == "S"
    assert abs(float(bot.state.open_positions["005930"].locked_profit_pct or 0.0) - 0.05) < 1e-9


def test_swing_stop_loss_requires_trend_break(tmp_path) -> None:
    code = "111111"
    asof = "20260216"
    now = datetime(2026, 2, 16, 10, 0)

    api = FakeAPI()
    api._quotes[code] = {"price": 96, "change_pct": -4.0}
    api._bars[(code, asof)] = pd.DataFrame(
        [
            {"date": "20260212", "close": 90, "volume": 1_000_000},
            {"date": "20260213", "close": 95, "volume": 1_000_000},
            {"date": "20260214", "close": 100, "volume": 1_000_000},
        ]
    )

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        swing_stop_loss_pct=-0.03,
        swing_sl_requires_trend_break=True,
        swing_trend_ma_window=3,
        swing_trend_lookback_bars=5,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.open_positions[code] = PositionState(
        type="S",
        entry_time="2026-02-14T09:10:00",
        entry_price=100.0,
        qty=10,
        highest_price=102.0,
        entry_date="20260214",
        bars_held=1,
    )

    # 손실률은 -4%지만, MA(=95) 위이므로 추세 훼손 아님 -> 즉시 손절 금지
    bot.monitor_positions(now=now)
    assert api.order_calls == []
    assert code in bot.state.open_positions

    # 동일 손실률에서 MA를 상회하지 못하게 만들어 추세 훼손 유도 -> 손절 실행
    api._bars[(code, asof)] = pd.DataFrame(
        [
            {"date": "20260212", "close": 110, "volume": 1_000_000},
            {"date": "20260213", "close": 108, "volume": 1_000_000},
            {"date": "20260214", "close": 106, "volume": 1_000_000},
        ]
    )
    bot.monitor_positions(now=now)

    assert any(call["side"] == "SELL" and call["code"] == code for call in api.order_calls)
    assert code not in bot.state.open_positions


def test_detect_intraday_cb_day_change_drop() -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    asof = "20260304"
    code = "069500"
    api._intraday[(code, asof)] = _make_intraday_bars(asof, [100.0, 99.9, 99.8], last_change_pct=-3.5)

    triggered, meta = detect_intraday_circuit_breaker(
        api,
        asof=asof,
        code=code,
        one_bar_drop_pct=-10.0,
        window_minutes=5,
        window_drop_pct=-10.0,
        day_change_pct=-3.0,
    )

    assert triggered is True
    assert meta.get("reason") == "DAY_CHANGE_DROP"


def test_detect_intraday_cb_last_bar_drop() -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    api = IntradayAPI()
    asof = "20260304"
    code = "069500"
    api._intraday[(code, asof)] = _make_intraday_bars(asof, [100.0, 100.3, 98.9])

    triggered, meta = detect_intraday_circuit_breaker(
        api,
        asof=asof,
        code=code,
        one_bar_drop_pct=-1.0,
        window_minutes=5,
        window_drop_pct=-10.0,
        day_change_pct=-10.0,
    )

    assert triggered is True
    assert meta.get("reason") == "INTRADAY_BAR_DROP"


def test_get_regime_reports_actual_recent_panic_date() -> None:
    asof = "20260312"
    api = FakeAPI()
    closes = [float(100 + idx) for idx in range(77)] + [166.0, 168.0, 170.0]
    api._bars[("069500", asof)] = _make_bars_from_closes(asof, closes)

    regime, panic_date = get_regime(api, asof)

    assert regime == "RISK_OFF"
    assert panic_date == "20260310"


def test_get_regime_uses_relaxed_default_vol_threshold_for_war_volatility() -> None:
    asof = "20260316"
    api = FakeAPI()
    closes = [100 + i for i in range(60)] + [
        160.0, 166.0, 161.0, 168.0, 162.0,
        170.0, 165.0, 172.0, 168.0, 174.0,
        171.0, 176.0, 170.0, 178.0, 173.0,
        180.0, 176.0, 182.0, 179.0, 184.0,
    ]
    api._bars[("069500", asof)] = _make_bars_from_closes(asof, closes)

    relaxed_regime, relaxed_panic_date = get_regime(api, asof)
    strict_regime, strict_panic_date = get_regime(api, asof, vol_threshold=0.03)

    assert relaxed_regime == "RISK_ON"
    assert relaxed_panic_date is None
    assert strict_regime == "RISK_OFF"
    assert strict_panic_date is None


def test_bot_keeps_original_panic_date_inside_recent_window(tmp_path) -> None:
    asof = "20260312"
    api = FakeAPI()
    closes = [float(100 + idx) for idx in range(77)] + [166.0, 168.0, 170.0]
    api._bars[("069500", asof)] = _make_bars_from_closes(asof, closes)

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.last_panic_date = "20260310"

    out = bot.run_once(now=datetime(2026, 3, 12, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert bot.state.last_panic_date == "20260310"


def test_bot_intraday_cb_forces_risk_off(tmp_path) -> None:
    class IntradayAPI(FakeAPI):
        def __init__(self) -> None:
            super().__init__()
            self._intraday: dict[tuple[str, str], pd.DataFrame] = {}

        def intraday_bars(self, code: str, asof: str, lookback: int = 120) -> pd.DataFrame:
            del lookback
            return self._intraday.get((code, asof), pd.DataFrame())

    asof = "20260304"
    api = IntradayAPI()
    api._bars[("069500", asof)] = _make_bars(asof, 80, 100.0, 1.0)
    api._intraday[("069500", asof)] = _make_intraday_bars(asof, [100.0, 100.4, 98.8])

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    out = bot.run_once(now=datetime(2026, 3, 4, 10, 5))

    assert out["status"] == "OK"
    assert out["regime"] == "RISK_OFF"
    assert bot.state.last_panic_date == asof
    assert int(bot.state.pass_reasons_today.get("RISK_OFF", 0)) >= 1


def test_runtime_loads_position_limit_overrides_from_env() -> None:
    with patch.dict(
        "os.environ",
        {
            "TRADING_ENGINE_MAX_SWING_POSITIONS": "2",
            "TRADING_ENGINE_MAX_DAY_POSITIONS": "2",
            "TRADING_ENGINE_MAX_TOTAL_POSITIONS": "3",
            "TRADING_ENGINE_MAX_SWING_ENTRIES_PER_WEEK": "4",
            "TRADING_ENGINE_MAX_SWING_ENTRIES_PER_DAY": "2",
            "TRADING_ENGINE_MAX_DAY_ENTRIES_PER_DAY": "2",
            "TRADING_ENGINE_DAY_STOPLOSS_EXCLUDE_AFTER_LOSSES": "3",
            "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MIN_DAY_CHANGE_PCT": "1.4",
            "TRADING_ENGINE_DAY_INTRADAY_TIGHT_BASE_MIN_WINDOW_CHANGE_PCT": "0.08",
            "TRADING_ENGINE_DAY_THEME_CANDIDATE_MAX_INJECTIONS": "4",
            "TRADING_ENGINE_DAY_THEME_CANDIDATE_MIN_SECTOR_SCORE": "0.45",
            "TRADING_ENGINE_USE_REALIZED_PROFIT_BUFFER": "0",
            "TRADING_ENGINE_SWING_PREFER_SECTOR_ETF_ON_THEME_DAY": "1",
            "TRADING_ENGINE_SWING_SECTOR_ETF_MIN_BREADTH": "3",
        },
        clear=False,
    ):
        cfg = _load_config_from_env()

    assert cfg.max_swing_positions == 2
    assert cfg.max_day_positions == 2
    assert cfg.max_total_positions == 3
    assert cfg.max_swing_entries_per_week == 4
    assert cfg.max_swing_entries_per_day == 2
    assert cfg.max_day_entries_per_day == 2
    assert cfg.day_stoploss_exclude_after_losses == 3
    assert cfg.day_intraday_tight_base_min_day_change_pct == 1.4
    assert cfg.day_intraday_tight_base_min_window_change_pct == 0.08
    assert cfg.day_theme_candidate_max_injections == 4
    assert cfg.day_theme_candidate_min_sector_score == 0.45
    assert cfg.use_realized_profit_buffer is False
    assert cfg.swing_prefer_sector_etf_on_theme_day is True
    assert cfg.swing_sector_etf_min_breadth == 3
