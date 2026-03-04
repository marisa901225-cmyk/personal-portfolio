from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.news_sentiment import NewsSentimentSignal
from backend.services.trading_engine.strategy import (
    Candidates,
    _score_day_row,
    build_candidates,
    pick_daytrade,
    pick_swing,
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

    def _candidates_with_swing(self, model: pd.DataFrame, etf: pd.DataFrame) -> Candidates:
        return Candidates(
            asof="20260227",
            popular=pd.DataFrame(),
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

    @patch("backend.services.trading_engine.strategy._score_day_row", return_value=80.0)
    def test_pick_daytrade_sorts_change_pct_as_numeric(self, _mock_score) -> None:
        pool = pd.DataFrame(
            [
                {"code": "A", "name": "Alpha", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "9.9"},
                {"code": "B", "name": "Beta", "is_etf": False, "avg_value_5d": "10000000000", "change_pct": "10.2"},
            ]
        )
        cfg = TradeEngineConfig(include_etf=False)

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


if __name__ == "__main__":
    unittest.main()
