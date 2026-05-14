from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd

from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.strategy import (
    Candidates,
    _merge_candidates,
    build_candidates,
    exclude_candidate_codes,
)

from .trading_strategy_helpers import TradingStrategyTestCase


class TradingStrategyCandidateTests(TradingStrategyTestCase):
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
                {"code": "034020", "name": "두산에너지빌리티", "avg_value_5d": 3, "close": 1, "change_pct": 1, "is_etf": False},
                {"code": "111111", "name": "Alpha", "avg_value_5d": 2, "close": 1, "change_pct": 1, "is_etf": False},
            ]
        )
        mock_model.return_value = pd.DataFrame(
            [
                {"code": "229200", "name": "KOSDAQ150", "avg_value_20d": 10, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": True},
                {"code": "034020", "name": "두산에너지빌리티", "avg_value_20d": 30, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": False},
                {"code": "222222", "name": "Beta", "avg_value_20d": 20, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": False},
            ]
        )
        mock_etf.return_value = pd.DataFrame(
            [
                {"code": "333333", "name": "ETF A", "avg_value_20d": 30, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": True},
                {"code": "069500", "name": "KOSPI200", "avg_value_20d": 40, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": True},
                {"code": "034020", "name": "두산에너지빌리티 ETF?", "avg_value_20d": 50, "ma20": 1, "ma60": 1, "close": 1, "change_pct": 1, "is_etf": True},
            ]
        )

        cfg = TradeEngineConfig(
            include_etf=True,
            quote_score_limit=10,
            market_proxy_code="069500",
            kosdaq_proxy_code="229200",
            permanent_excluded_entry_codes=("034020",),
        )

        result = build_candidates(api=object(), asof="20260227", config=cfg)

        self.assertNotIn("069500", set(result.popular["code"]))
        self.assertNotIn("034020", set(result.popular["code"]))
        self.assertNotIn("229200", set(result.model["code"]))
        self.assertNotIn("034020", set(result.model["code"]))
        self.assertNotIn("069500", set(result.etf["code"]))
        self.assertNotIn("034020", set(result.etf["code"]))
        self.assertNotIn("069500", set(result.merged["code"]))
        self.assertNotIn("229200", set(result.merged["code"]))
        self.assertNotIn("034020", set(result.merged["code"]))
        self.assertNotIn("069500", set(result.quote_codes))
        self.assertNotIn("229200", set(result.quote_codes))
        self.assertNotIn("034020", set(result.quote_codes))

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


if __name__ == "__main__":
    unittest.main()
