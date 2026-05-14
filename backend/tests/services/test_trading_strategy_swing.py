from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.strategy import (
    pick_swing,
    rank_swing_codes,
)

from .trading_strategy_helpers import TradingStrategyTestCase


class TradingStrategySwingTests(TradingStrategyTestCase):
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
        mock_score.side_effect = lambda row, *args, **kwargs: 100.0 if row["code"] == "379800" else 90.0

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

    def test_rank_swing_includes_strong_day_theme_leaders(self) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "BASE01",
                    "name": "기준종목",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.2,
                    "is_etf": False,
                    "trend_tier": "strict",
                }
            ]
        )
        popular_pool = pd.DataFrame(
            [
                {
                    "code": "SEMI01",
                    "name": "KODEX 반도체",
                    "avg_value_5d": 180_000_000_000,
                    "close": 106,
                    "change_pct": 6.5,
                    "is_etf": True,
                    "sector_bucket_selected": True,
                    "theme_sector": "semiconductor",
                }
            ]
        )
        cfg = TradeEngineConfig(
            swing_include_day_theme_leaders=True,
            swing_day_theme_leader_min_change_pct=2.0,
            swing_day_theme_leader_min_avg_value_5d=30_000_000_000,
            swing_day_theme_leader_bonus=36.0,
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame(), popular=popular_pool)

        ranked = rank_swing_codes(candidates, quotes={}, config=cfg)

        self.assertEqual(ranked[0], "SEMI01")
        self.assertIn("BASE01", ranked)

    def test_rank_swing_ignores_plain_day_popular_rows(self) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "BASE01",
                    "name": "기준종목",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.2,
                    "is_etf": False,
                    "trend_tier": "strict",
                }
            ]
        )
        popular_pool = pd.DataFrame(
            [
                {
                    "code": "PLAIN1",
                    "name": "무테마",
                    "avg_value_5d": 180_000_000_000,
                    "close": 106,
                    "change_pct": 6.5,
                    "is_etf": False,
                }
            ]
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame(), popular=popular_pool)

        ranked = rank_swing_codes(candidates, quotes={}, config=TradeEngineConfig())

        self.assertEqual(ranked[0], "BASE01")
        self.assertNotIn("PLAIN1", ranked)

    def test_rank_swing_excludes_stocks_above_one_share_budget(self) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "003230",
                    "name": "고가주",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 100_000,
                    "change_pct": 1.2,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "CHEAP1",
                    "name": "예산내",
                    "avg_value_20d": 500_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 790_000,
                    "change_pct": 1.0,
                    "is_etf": False,
                    "trend_tier": "relaxed",
                },
            ]
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame())
        quotes = {
            "003230": {"price": 1_400_000, "change_pct": 1.2},
            "CHEAP1": {"price": 790_000, "change_pct": 1.0},
        }

        ranked = rank_swing_codes(
            candidates,
            quotes=quotes,
            config=TradeEngineConfig(initial_capital=1_000_000, swing_cash_ratio=0.8),
        )

        self.assertEqual(ranked[0], "CHEAP1")
        self.assertNotIn("003230", ranked)

    def test_rank_swing_excludes_cosmetics_names(self) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "278470",
                    "name": "에이피알",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 104,
                    "change_pct": 1.2,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "SEMI01",
                    "name": "반도체리더",
                    "avg_value_20d": 500_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 103,
                    "change_pct": 1.0,
                    "is_etf": False,
                    "trend_tier": "relaxed",
                },
            ]
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame())

        ranked = rank_swing_codes(candidates, quotes={}, config=TradeEngineConfig())

        self.assertEqual(ranked[0], "SEMI01")
        self.assertNotIn("278470", ranked)

    def test_rank_swing_excludes_cosmetics_day_theme_leader(self) -> None:
        model_pool = pd.DataFrame(
            [
                {
                    "code": "SEMI01",
                    "name": "반도체리더",
                    "avg_value_20d": 500_000_000_000,
                    "ma20": 100,
                    "ma60": 95,
                    "close": 103,
                    "change_pct": 1.0,
                    "is_etf": False,
                    "trend_tier": "relaxed",
                }
            ]
        )
        popular_pool = pd.DataFrame(
            [
                {
                    "code": "APR001",
                    "name": "에이피알",
                    "avg_value_5d": 180_000_000_000,
                    "close": 106,
                    "change_pct": 6.5,
                    "is_etf": False,
                    "sector_bucket_selected": True,
                    "theme_sector": "beauty",
                }
            ]
        )
        candidates = self._candidates_with_swing(model=model_pool, etf=pd.DataFrame(), popular=popular_pool)

        ranked = rank_swing_codes(candidates, quotes={}, config=TradeEngineConfig())

        self.assertEqual(ranked[0], "SEMI01")
        self.assertNotIn("APR001", ranked)


if __name__ == "__main__":
    unittest.main()
