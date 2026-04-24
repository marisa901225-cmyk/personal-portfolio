from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.news_sentiment import NewsSentimentSignal
from backend.services.trading_engine.strategy import (
    Candidates,
    _merge_candidates,
    _score_day_row,
    build_candidates,
    exclude_candidate_codes,
    pick_daytrade,
    pick_swing,
    rank_daytrade_codes,
)


class TradingStrategyTests(unittest.TestCase):
    def _candidates_with_popular(self, popular: pd.DataFrame) -> Candidates:
        return Candidates(
            asof="20260227",
            popular=popular,
            model=pd.DataFrame(),
            etf=pd.DataFrame(),
            merged=pd.DataFrame(),
            quote_codes=[],
        )

    def _candidates_with_swing(
        self,
        model: pd.DataFrame,
        etf: pd.DataFrame,
        popular: pd.DataFrame | None = None,
    ) -> Candidates:
        return Candidates(
            asof="20260227",
            popular=popular if popular is not None else pd.DataFrame(),
            model=model,
            etf=etf,
            merged=pd.DataFrame(),
            quote_codes=[],
        )

    @patch("backend.services.trading_engine.strategy.etf_swing_screener")
    @patch("backend.services.trading_engine.strategy.model_screener")
    @patch("backend.services.trading_engine.strategy.popular_screener")
    def test_build_candidates_drops_proxy_codes(
        self,
        mock_popular,
        mock_model,
        mock_etf,
    ) -> None:
        mock_popular.return_value = pd.DataFrame(
            [
                {"code": "069500", "name": "KOSPI200", "avg_value_5d": 1, "close": 1, "change_pct": 1, "is_etf": True},
                {"code": "111111", "name": "Alpha", "avg_value_5d": 2, "close": 1, "change_pct": 1, "is_etf": False},
            ]
        )
        mock_model.return_value = pd.DataFrame(
            [
                {"code": "229200", "name": "KOSDAQ150", "avg_value_20d": 10, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": True},
                {"code": "222222", "name": "Beta", "avg_value_20d": 20, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": False},
            ]
        )
        mock_etf.return_value = pd.DataFrame(
            [
                {"code": "333333", "name": "ETF A", "avg_value_20d": 30, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": True},
                {"code": "069500", "name": "KOSPI200", "avg_value_20d": 40, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": True},
            ]
        )

        cfg = TradeEngineConfig(
            include_etf=True,
            quote_score_limit=10,
            market_proxy_code="069500",
            kosdaq_proxy_code="229200",
        )

        result = build_candidates(api=object(), asof="20260227", config=cfg)

        self.assertNotIn("069500", set(result.popular["code"]))
        self.assertNotIn("229200", set(result.model["code"]))
        self.assertNotIn("069500", set(result.etf["code"]))
        self.assertNotIn("069500", set(result.merged["code"]))
        self.assertNotIn("229200", set(result.merged["code"]))
        self.assertNotIn("069500", set(result.quote_codes))
        self.assertNotIn("229200", set(result.quote_codes))

    def test_merge_candidates_prioritizes_theme_injected_rows(self) -> None:
        popular = pd.DataFrame(
            [
                {
                    "code": "333333",
                    "name": "한싹",
                    "avg_value_5d": 35_000_000_000,
                    "close": 10_000,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "theme_injected": True,
                    "theme_sector": "cyber_security",
                }
            ]
        )
        model = pd.DataFrame(
            [
                {
                    "code": "111111",
                    "name": "대형주A",
                    "avg_value_20d": 800_000_000_000,
                    "ma20": 1,
                    "ma60": 1,
                    "close": 1,
                    "change_pct": 1.0,
                    "is_etf": False,
                },
                {
                    "code": "222222",
                    "name": "대형주B",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 1,
                    "ma60": 1,
                    "close": 1,
                    "change_pct": 1.0,
                    "is_etf": False,
                },
            ]
        )

        merged = _merge_candidates(popular, model, pd.DataFrame())

        self.assertEqual(str(merged.iloc[0]["code"]), "333333")
        self.assertIs(bool(merged.iloc[0]["theme_injected"]), True)
        self.assertEqual(str(merged.iloc[0]["theme_sector"]), "cyber_security")

    def test_merge_candidates_uses_best_available_liquidity_across_sources(self) -> None:
        popular = pd.DataFrame(
            [
                {
                    "code": "444444",
                    "name": "인기주",
                    "avg_value_5d": 120_000_000_000,
                    "close": 10_000,
                    "change_pct": 3.0,
                    "is_etf": False,
                }
            ]
        )
        model = pd.DataFrame(
            [
                {
                    "code": "555555",
                    "name": "모델주",
                    "avg_value_20d": 90_000_000_000,
                    "ma20": 1,
                    "ma60": 1,
                    "close": 1,
                    "change_pct": 1.0,
                    "is_etf": False,
                }
            ]
        )

        merged = _merge_candidates(popular, model, pd.DataFrame())

        self.assertEqual(merged["code"].tolist(), ["444444", "555555"])

    def test_merge_candidates_rotates_other_sector_before_same_sector_repeat(self) -> None:
        popular = pd.DataFrame(
            [
                {
                    "code": "SEMI1",
                    "name": "반도체 대장주",
                    "avg_value_5d": 120_000_000_000,
                    "close": 10_000,
                    "change_pct": 5.0,
                    "is_etf": False,
                },
                {
                    "code": "SEMI2",
                    "name": "반도체 후속주",
                    "avg_value_5d": 110_000_000_000,
                    "close": 9_500,
                    "change_pct": 4.5,
                    "is_etf": False,
                },
                {
                    "code": "SEC1",
                    "name": "보안 대장주",
                    "avg_value_5d": 100_000_000_000,
                    "close": 8_000,
                    "change_pct": 4.0,
                    "is_etf": False,
                },
            ]
        )

        merged = _merge_candidates(
            popular,
            pd.DataFrame(),
            pd.DataFrame(),
            sector_keywords={
                "semiconductor": ("반도체",),
                "cyber_security": ("보안",),
            },
        )

        self.assertEqual(merged["code"].tolist(), ["SEMI1", "SEC1", "SEMI2"])

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_prefers_stock_within_relative_threshold(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "ETF01", "name": "ETF", "is_etf": True, "avg_value_5d": "60000000000", "change_pct": "2.0", "mock_score": 100.0},
                {"code": "STK01", "name": "Stock", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "1.8", "mock_score": 95.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=True,
            day_etf_min_avg_value_5d=50_000_000_000,
            day_stock_prefer_threshold=0.95,
        )

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "STK01")

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_keeps_etf_when_stock_below_threshold(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "ETF01", "name": "ETF", "is_etf": True, "avg_value_5d": "60000000000", "change_pct": "2.0", "mock_score": 100.0},
                {"code": "STK01", "name": "Stock", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "1.8", "mock_score": 94.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=True,
            day_etf_min_avg_value_5d=50_000_000_000,
            day_stock_prefer_threshold=0.95,
        )

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "ETF01")

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_rank_daytrade_codes_keeps_followup_candidates_for_fallback(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "EXPENSIVE", "name": "Expensive", "is_etf": False, "avg_value_5d": "90000000000", "change_pct": "6.0", "mock_score": 120.0},
                {"code": "AFFORD01", "name": "Affordable", "is_etf": False, "avg_value_5d": "80000000000", "change_pct": "5.0", "mock_score": 110.0},
                {"code": "ETF01", "name": "ETF", "is_etf": True, "avg_value_5d": "70000000000", "change_pct": "4.0", "mock_score": 100.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(include_etf=True, day_etf_min_avg_value_5d=50_000_000_000)
        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes={}, config=cfg)

        self.assertEqual(ranked, ["EXPENSIVE", "AFFORD01", "ETF01"])

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_rank_daytrade_codes_excludes_small_stock_under_quality_floor(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {
                    "code": "SMALL01",
                    "name": "Small",
                    "is_etf": False,
                    "mcap": "400000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "3.0",
                    "mock_score": 120.0,
                },
                {
                    "code": "LARGE01",
                    "name": "Large",
                    "is_etf": False,
                    "mcap": "1200000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "2.5",
                    "mock_score": 110.0,
                },
                {
                    "code": "ETF01",
                    "name": "ETF",
                    "is_etf": True,
                    "mcap": "0",
                    "avg_value_5d": "70000000000",
                    "change_pct": "2.0",
                    "mock_score": 100.0,
                },
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=True,
            day_etf_min_avg_value_5d=50_000_000_000,
            day_stock_min_avg_value_5d=30_000_000_000,
            day_stock_min_mcap=1_000_000_000_000,
        )

        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes={}, config=cfg)

        self.assertEqual(ranked, ["LARGE01", "ETF01"])

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_rank_daytrade_codes_excludes_live_management_warning_risk_candidates(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {
                    "code": "MGMT01",
                    "name": "Management",
                    "is_etf": False,
                    "mcap": "1200000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "3.0",
                    "mock_score": 130.0,
                },
                {
                    "code": "WARN01",
                    "name": "Warning",
                    "is_etf": False,
                    "mcap": "1200000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "2.8",
                    "mock_score": 120.0,
                },
                {
                    "code": "RISK01",
                    "name": "Risk",
                    "is_etf": False,
                    "mcap": "1200000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "2.6",
                    "mock_score": 110.0,
                },
                {
                    "code": "OK001",
                    "name": "Okay",
                    "is_etf": False,
                    "mcap": "1200000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "2.4",
                    "mock_score": 100.0,
                },
            ]
        )
        quotes = {
            "MGMT01": {"management_issue_code": "Y", "market_warning_code": "00"},
            "WARN01": {"management_issue_code": "N", "market_warning_code": "02"},
            "RISK01": {"management_issue_code": "N", "market_warning_code": "03"},
            "OK001": {"management_issue_code": "N", "market_warning_code": "00"},
        }
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=False,
            day_stock_min_avg_value_5d=30_000_000_000,
            day_stock_min_mcap=1_000_000_000_000,
        )

        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes=quotes, config=cfg)

        self.assertEqual(ranked, ["OK001"])

    @patch("backend.services.trading_engine.strategy._day_intraday_structure_score", return_value=0.0)
    def test_rank_daytrade_codes_prefers_candidate_with_strong_industry_trend(self, _mock_intraday) -> None:
        pool = pd.DataFrame(
            [
                {
                    "code": "111111",
                    "name": "StrongIndustry",
                    "is_etf": False,
                    "mcap": "1200000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "2.0",
                    "close": 10000,
                    "retrace_from_high_10d_pct": -2.0,
                    "industry_bucket_name": "창업투자",
                    "industry_close": 1020.0,
                    "industry_ma5": 1010.0,
                    "industry_ma20": 980.0,
                    "industry_day_change_pct": 1.2,
                    "industry_5d_change_pct": 3.0,
                },
                {
                    "code": "222222",
                    "name": "WeakIndustry",
                    "is_etf": False,
                    "mcap": "1200000000000",
                    "avg_value_5d": "60000000000",
                    "change_pct": "2.0",
                    "close": 10000,
                    "retrace_from_high_10d_pct": -2.0,
                    "industry_bucket_name": "통신장비",
                    "industry_close": 970.0,
                    "industry_ma5": 975.0,
                    "industry_ma20": 1005.0,
                    "industry_day_change_pct": -1.1,
                    "industry_5d_change_pct": -3.5,
                },
            ]
        )
        quotes = {
            "111111": {"price": 10000, "open": 9950, "high": 10050, "low": 9900, "change_pct": 2.0},
            "222222": {"price": 10000, "open": 9950, "high": 10050, "low": 9900, "change_pct": 2.0},
        }
        cfg = TradeEngineConfig(
            include_etf=False,
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
        )

        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes=quotes, config=cfg)

        self.assertEqual(ranked[0], "111111")

    def test_rank_daytrade_codes_realtime_strength_weight_overrides_liquidity_bias(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "code": "WEAKBIG",
                    "name": "Weak Big",
                    "is_etf": False,
                    "mcap": "1500000000000",
                    "avg_value_5d": "500000000000",
                    "change_pct": "1.2",
                    "close": 101.0,
                    "retrace_from_high_10d_pct": -2.0,
                },
                {
                    "code": "STRONG",
                    "name": "Strong Lead",
                    "is_etf": False,
                    "mcap": "1500000000000",
                    "avg_value_5d": "70000000000",
                    "change_pct": "3.4",
                    "close": 106.0,
                    "retrace_from_high_10d_pct": -1.0,
                },
            ]
        )
        quotes = {
            "WEAKBIG": {"price": 101.0, "open": 101.0, "high": 106.0, "low": 100.0, "change_pct": 1.2},
            "STRONG": {"price": 106.0, "open": 102.0, "high": 106.5, "low": 101.5, "change_pct": 3.4},
        }
        cfg = TradeEngineConfig(
            include_etf=False,
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
            day_intraday_strength_weight=1.8,
        )

        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes=quotes, config=cfg)

        self.assertEqual(ranked[:2], ["STRONG", "WEAKBIG"])

    def test_rank_daytrade_codes_allows_strong_momentum_chase_above_default_cap(self) -> None:
        pool = pd.DataFrame(
            [
                {
                    "code": "CHASE1",
                    "name": "Chase Leader",
                    "is_etf": False,
                    "mcap": "1600000000000",
                    "avg_value_5d": "90000000000",
                    "change_pct": "18.0",
                    "close": 118.0,
                    "retrace_from_high_10d_pct": -1.0,
                },
                {
                    "code": "SAFE01",
                    "name": "Safe Follower",
                    "is_etf": False,
                    "mcap": "1600000000000",
                    "avg_value_5d": "85000000000",
                    "change_pct": "5.0",
                    "close": 105.0,
                    "retrace_from_high_10d_pct": -1.5,
                },
            ]
        )
        quotes = {
            "CHASE1": {"price": 118.0, "open": 109.0, "high": 119.0, "low": 108.5, "change_pct": 18.0},
            "SAFE01": {"price": 105.0, "open": 102.0, "high": 106.0, "low": 101.0, "change_pct": 5.0},
        }
        cfg = TradeEngineConfig(
            include_etf=False,
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
            day_max_change_pct=6.0,
            day_momentum_chase_max_change_pct=26.0,
            day_momentum_chase_min_intraday_score=3.0,
        )

        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes=quotes, config=cfg)

        self.assertEqual(ranked[0], "CHASE1")

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_rank_daytrade_promotes_only_top_stock_preference(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "ETF_TOP", "name": "ETF top", "is_etf": True, "avg_value_5d": "70000000000", "change_pct": "2.0", "mock_score": 100.0},
                {"code": "STK_TOP", "name": "Stock top", "is_etf": False, "avg_value_5d": "30000000000", "change_pct": "1.8", "mock_score": 95.0},
                {"code": "ETF_NEXT", "name": "ETF next", "is_etf": True, "avg_value_5d": "65000000000", "change_pct": "1.7", "mock_score": 94.0},
                {"code": "STK_LOW", "name": "Stock low", "is_etf": False, "avg_value_5d": "20000000000", "change_pct": "1.1", "mock_score": 70.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=True,
            day_etf_min_avg_value_5d=50_000_000_000,
            day_stock_prefer_threshold=0.95,
        )

        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes={}, config=cfg)

        self.assertEqual(ranked, ["STK_TOP", "ETF_TOP", "ETF_NEXT", "STK_LOW"])

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_rank_daytrade_codes_rotates_other_sector_before_same_sector_repeat(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "SEMI1", "name": "반도체 대장주", "is_etf": False, "avg_value_5d": "90000000000", "change_pct": "5.0", "mock_score": 110.0},
                {"code": "SEMI2", "name": "반도체 후속주", "is_etf": False, "avg_value_5d": "85000000000", "change_pct": "4.8", "mock_score": 108.0},
                {"code": "SEC1", "name": "보안 대장주", "is_etf": False, "avg_value_5d": "80000000000", "change_pct": "4.6", "mock_score": 106.0},
                {"code": "BIO1", "name": "바이오 대장주", "is_etf": False, "avg_value_5d": "75000000000", "change_pct": "4.4", "mock_score": 104.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config, news_signal=None: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=False,
            day_max_change_pct=12.0,
        )
        news_signal = NewsSentimentSignal(
            market_score=0.2,
            sector_scores={
                "semiconductor": 0.9,
                "cyber_security": 0.8,
                "bio_healthcare": 0.7,
            },
            sector_keywords={
                "semiconductor": ("반도체",),
                "cyber_security": ("보안",),
                "bio_healthcare": ("바이오",),
            },
            article_count=20,
        )

        ranked = rank_daytrade_codes(
            self._candidates_with_popular(pool),
            quotes={},
            config=cfg,
            news_signal=news_signal,
        )

        self.assertEqual(ranked, ["SEMI1", "SEC1", "BIO1", "SEMI2"])

    @patch("backend.services.trading_engine.strategy._score_day_row", return_value=80.0)
    def test_pick_daytrade_sorts_change_pct_as_numeric(self, _mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "A", "name": "Alpha", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "9.9"},
                {"code": "B", "name": "Beta", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "10.2"},
            ]
        )
        cfg = TradeEngineConfig(include_etf=False, day_max_change_pct=11.0)

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "B")

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_filters_etf_by_numeric_avg_value(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "ETF_LOW", "name": "ETF low", "is_etf": True, "avg_value_5d": "40000000000", "change_pct": "3.0", "mock_score": 120.0},
                {"code": "ETF_OK", "name": "ETF ok", "is_etf": True, "avg_value_5d": "60000000000", "change_pct": "2.0", "mock_score": 90.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=True,
            day_etf_min_avg_value_5d=50_000_000_000,
        )

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "ETF_OK")

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_excludes_hard_drop_candidates(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "DROP10", "name": "Dropper", "is_etf": False, "avg_value_5d": "90000000000", "change_pct": "-10.0", "mock_score": 200.0},
                {"code": "SAFE01", "name": "Safe", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "1.2", "mock_score": 80.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=False,
            day_hard_drop_exclude_pct=-6.0,
        )

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "SAFE01")

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_excludes_overheated_chasers(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "CHASE9", "name": "Chaser", "is_etf": False, "avg_value_5d": "90000000000", "change_pct": "9.2", "mock_score": 150.0},
                {"code": "SAFE02", "name": "Safer", "is_etf": False, "avg_value_5d": "70000000000", "change_pct": "2.4", "mock_score": 100.0},
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=False,
            day_max_change_pct=6.0,
        )

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "SAFE02")

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_excludes_deeply_retraced_recent_high_candidates(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {
                    "code": "FADE10",
                    "name": "광통신 급락주",
                    "is_etf": False,
                    "avg_value_5d": "90000000000",
                    "change_pct": "2.0",
                    "retrace_from_high_10d_pct": "-24.0",
                    "mock_score": 150.0,
                },
                {
                    "code": "SAFE10",
                    "name": "추세 유지주",
                    "is_etf": False,
                    "avg_value_5d": "70000000000",
                    "change_pct": "2.4",
                    "retrace_from_high_10d_pct": "-4.0",
                    "mock_score": 100.0,
                },
            ]
        )
        mock_score.side_effect = lambda row, quotes, config: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=False,
            day_max_change_pct=6.0,
            day_recent_high_retrace_10d_min_pct=-12.0,
        )

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "SAFE10")

    def test_exclude_candidate_codes_removes_stoploss_symbols_from_all_views(self) -> None:
        candidates = Candidates(
            asof="20260407",
            popular=pd.DataFrame(
                [
                    {"code": "011930", "name": "신성이엔지", "avg_value_5d": 100, "close": 1000, "change_pct": 5.0, "is_etf": False},
                    {"code": "005930", "name": "삼성전자", "avg_value_5d": 90, "close": 900, "change_pct": 2.0, "is_etf": False},
                ]
            ),
            model=pd.DataFrame(
                [
                    {"code": "011930", "name": "신성이엔지", "avg_value_20d": 200, "ma20": 100, "ma60": 95, "close": 101, "change_pct": 5.0, "is_etf": False},
                ]
            ),
            etf=pd.DataFrame(),
            merged=pd.DataFrame(
                [
                    {"code": "011930", "name": "신성이엔지"},
                    {"code": "005930", "name": "삼성전자"},
                ]
            ),
            quote_codes=["011930", "005930"],
        )

        filtered = exclude_candidate_codes(candidates, {"011930"})

        self.assertEqual(set(filtered.popular["code"]), {"005930"})
        self.assertTrue(filtered.model.empty)
        self.assertEqual(set(filtered.merged["code"]), {"005930"})
        self.assertEqual(filtered.quote_codes, ["005930"])

    def test_pick_swing_etf_fallback_avoids_deep_losers(self) -> None:
        etf_pool = pd.DataFrame(
            [
                {
                    "code": "ETF_BAD",
                    "name": "TIGER 반도체TOP10",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 96,
                    "change_pct": -8.0,
                    "is_etf": True,
                },
                {
                    "code": "ETF_OK",
                    "name": "KODEX 방산TOP10",
                    "avg_value_20d": 500_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 102,
                    "change_pct": 1.5,
                    "is_etf": True,
                },
            ]
        )

        cfg = TradeEngineConfig(
            allow_etf_swing_fallback=True,
            swing_hard_drop_exclude_pct=-6.0,
            swing_etf_fallback_min_change_pct=-1.0,
        )
        candidates = self._candidates_with_swing(model=pd.DataFrame(), etf=etf_pool)

        picked = pick_swing(candidates, quotes={}, config=cfg)
        self.assertEqual(picked, "ETF_OK")

    @patch("backend.services.trading_engine.strategy._score_swing_row")
    def test_pick_swing_etf_fallback_excludes_broad_market_etf(self, mock_score) -> None:
        etf_pool = pd.DataFrame(
            [
                {
                    "code": "379800",
                    "name": "KODEX 미국S&P500",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 110.0,
                    "change_pct": 1.2,
                    "is_etf": True,
                },
                {
                    "code": "ETF_SECTOR",
                    "name": "KODEX 반도체",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 98.0,
                    "ma60": 93.0,
                    "close": 108.0,
                    "change_pct": 1.1,
                    "is_etf": True,
                },
            ]
        )
        mock_score.side_effect = lambda row, quotes, config, news_signal=None: 100.0 if row["code"] == "379800" else 90.0

        cfg = TradeEngineConfig(
            allow_etf_swing_fallback=True,
            swing_hard_drop_exclude_pct=-6.0,
            swing_etf_fallback_min_change_pct=-1.0,
        )
        candidates = self._candidates_with_swing(model=pd.DataFrame(), etf=etf_pool)

        picked = pick_swing(candidates, quotes={}, config=cfg)
        self.assertEqual(picked, "ETF_SECTOR")

    def test_pick_swing_prefers_strict_model_setup_over_relaxed(self) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "STRICT01",
                    "name": "Strict",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "RELAX01",
                    "name": "Relaxed",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.5,
                    "is_etf": False,
                    "trend_tier": "relaxed",
                },
            ]
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame())

        picked = pick_swing(candidates, quotes={}, config=TradeEngineConfig())
        self.assertEqual(picked, "STRICT01")

    @patch("backend.services.trading_engine.strategy._swing_quote_structure_score", return_value=0.0)
    def test_pick_swing_prefers_stronger_industry_trend(self, _mock_quote_structure) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "STRONG01",
                    "name": "Strong",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                    "industry_bucket_name": "창업투자",
                    "industry_close": 1020.0,
                    "industry_ma5": 1010.0,
                    "industry_ma20": 980.0,
                    "industry_day_change_pct": 0.8,
                    "industry_5d_change_pct": 5.0,
                },
                {
                    "code": "WEAK01",
                    "name": "Weak",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                    "industry_bucket_name": "통신장비",
                    "industry_close": 970.0,
                    "industry_ma5": 975.0,
                    "industry_ma20": 1005.0,
                    "industry_day_change_pct": -0.8,
                    "industry_5d_change_pct": -4.0,
                },
            ]
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame())

        picked = pick_swing(candidates, quotes={}, config=TradeEngineConfig())
        self.assertEqual(picked, "STRONG01")

    def test_pick_swing_prefers_popular_liquidity_leader_when_trend_scores_are_similar(self) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "LIQ001",
                    "name": "LiquidityLeader",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "PLAIN1",
                    "name": "PlainStock",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        )
        popular_pool = pd.DataFrame(
            [
                {
                    "code": "LIQ001",
                    "name": "LiquidityLeader",
                    "avg_value_5d": 140_000_000_000,
                    "change_pct": 3.0,
                    "legacy_top10_selected": True,
                    "value_rank_5d_top10": 1,
                },
                {
                    "code": "PLAIN1",
                    "name": "PlainStock",
                    "avg_value_5d": 70_000_000_000,
                    "change_pct": 1.0,
                    "legacy_top10_selected": False,
                    "value_rank_5d_top10": None,
                },
            ]
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame(), popular=popular_pool)

        picked = pick_swing(candidates, quotes={}, config=TradeEngineConfig())
        self.assertEqual(picked, "LIQ001")

    def test_score_day_row_applies_sector_news_bonus(self) -> None:
        row = pd.Series(
            {
                "code": "005930",
                "name": "삼성전자",
                "_avg_value_5d_num": 80_000_000_000,
                "_change_pct_num": 2.0,
                "_is_etf": False,
            }
        )
        cfg = TradeEngineConfig(
            news_day_weight=6.0,
            news_market_fallback_ratio=0.4,
        )
        news_signal = NewsSentimentSignal(
            market_score=-0.5,
            sector_scores={"semiconductor": 1.0},
            sector_keywords={"semiconductor": ("삼성", "반도체")},
            article_count=40,
        )

        score_without_news = _score_day_row(row, quotes={}, config=cfg, news_signal=None)
        score_with_news = _score_day_row(row, quotes={}, config=cfg, news_signal=news_signal)

        self.assertAlmostEqual(score_with_news - score_without_news, 6.0, places=6)

    def test_score_day_row_uses_market_fallback_when_no_sector_match(self) -> None:
        row = pd.Series(
            {
                "code": "000001",
                "name": "알파컴퍼니",
                "_avg_value_5d_num": 80_000_000_000,
                "_change_pct_num": 2.0,
                "_is_etf": False,
            }
        )
        cfg = TradeEngineConfig(
            news_day_weight=6.0,
            news_market_fallback_ratio=0.5,
        )
        news_signal = NewsSentimentSignal(
            market_score=1.0,
            sector_scores={"semiconductor": -1.0},
            sector_keywords={"semiconductor": ("삼성", "반도체")},
            article_count=40,
        )

        score_without_news = _score_day_row(row, quotes={}, config=cfg, news_signal=None)
        score_with_news = _score_day_row(row, quotes={}, config=cfg, news_signal=news_signal)

        # unmatched -> market_score * weight * fallback_ratio = 1.0 * 6.0 * 0.5
        self.assertAlmostEqual(score_with_news - score_without_news, 3.0, places=6)

    def test_score_day_row_rewards_high_current_value_rank(self) -> None:
        base_row = {
            "code": "000001",
            "name": "알파컴퍼니",
            "_avg_value_5d_num": 80_000_000_000,
            "_change_pct_num": 2.0,
            "_is_etf": False,
            "volume_rank": 15,
        }
        strong_row = pd.Series({**base_row, "value_rank": 1})
        weak_row = pd.Series({**base_row, "value_rank": 150})
        cfg = TradeEngineConfig()

        strong_score = _score_day_row(strong_row, quotes={}, config=cfg, news_signal=None)
        weak_score = _score_day_row(weak_row, quotes={}, config=cfg, news_signal=None)

        self.assertGreater(strong_score, weak_score)

    def test_score_day_row_rewards_high_hts_top_view_rank_softly(self) -> None:
        base_row = {
            "code": "000001",
            "name": "알파컴퍼니",
            "_avg_value_5d_num": 80_000_000_000,
            "_change_pct_num": 2.0,
            "_is_etf": False,
            "value_rank": 20,
            "volume_rank": 15,
        }
        strong_row = pd.Series({**base_row, "hts_view_rank": 1})
        weak_row = pd.Series({**base_row, "hts_view_rank": 20})
        cfg = TradeEngineConfig(day_hts_top_view_top_n=20, day_hts_top_view_bonus_max=3.0)

        strong_score = _score_day_row(strong_row, quotes={}, config=cfg, news_signal=None)
        weak_score = _score_day_row(weak_row, quotes={}, config=cfg, news_signal=None)

        self.assertGreater(strong_score, weak_score)


if __name__ == "__main__":
    unittest.main()
