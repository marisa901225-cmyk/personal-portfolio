from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.news_sentiment import NewsSentimentSignal
from backend.services.trading_engine.strategy import (
    _score_day_row,
    pick_daytrade,
    rank_daytrade_codes,
)

from .trading_strategy_helpers import TradingStrategyTestCase


class TradingStrategyDayTests(TradingStrategyTestCase):
    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_prefers_stock_within_relative_threshold(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "ETF01", "name": "ETF", "is_etf": True, "avg_value_5d": "60000000000", "change_pct": "2.0", "mock_score": 100.0},
                {"code": "STK01", "name": "Stock", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "1.8", "mock_score": 95.0},
            ]
        )
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

        cfg = TradeEngineConfig(include_etf=True, day_etf_min_avg_value_5d=50_000_000_000)
        ranked = rank_daytrade_codes(self._candidates_with_popular(pool), quotes={}, config=cfg)

        self.assertEqual(ranked, ["EXPENSIVE", "AFFORD01", "ETF01"])

    @patch("backend.services.trading_engine.strategy._score_day_row")
    def test_pick_daytrade_excludes_candidates_above_day_slot_budget(self, mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "051910", "name": "LG화학", "is_etf": False, "avg_value_5d": "90000000000", "change_pct": "3.0", "mock_score": 130.0},
                {"code": "AFFORD1", "name": "Affordable", "is_etf": False, "avg_value_5d": "80000000000", "change_pct": "2.5", "mock_score": 90.0},
            ]
        )
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

        cfg = TradeEngineConfig(
            initial_capital=1_000_000,
            day_cash_ratio=0.20,
            include_etf=False,
        )
        quotes = {
            "051910": {"price": 320_000},
            "AFFORD1": {"price": 80_000},
        }

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes=quotes, config=cfg)
        self.assertEqual(picked, "AFFORD1")

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

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
        mock_score.side_effect = lambda row, *args, **kwargs: float(row["mock_score"])

        cfg = TradeEngineConfig(
            include_etf=False,
            day_max_change_pct=6.0,
            day_recent_high_retrace_10d_min_pct=-12.0,
        )

        picked = pick_daytrade(self._candidates_with_popular(pool), quotes={}, config=cfg)
        self.assertEqual(picked, "SAFE10")


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

    def test_score_day_row_caps_liquidity_bonus_within_top_value_group(self) -> None:
        base_row = {
            "code": "000001",
            "name": "알파컴퍼니",
            "_avg_value_5d_num": 80_000_000_000,
            "_change_pct_num": 2.0,
            "_is_etf": False,
            "volume_rank": 15,
        }
        top_row = pd.Series({**base_row, "value_rank": 1})
        same_group_row = pd.Series({**base_row, "value_rank": 9})
        cfg = TradeEngineConfig()

        top_score = _score_day_row(top_row, quotes={}, config=cfg, news_signal=None)
        same_group_score = _score_day_row(same_group_row, quotes={}, config=cfg, news_signal=None)

        self.assertEqual(top_score, same_group_score)

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
