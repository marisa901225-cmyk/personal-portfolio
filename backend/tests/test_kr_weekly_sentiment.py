from __future__ import annotations

import unittest

from backend.services.economy.kr_weekly_sentiment import (
    _compute_futures_weekly_features,
    _compute_options_features,
    _normalize_daily_rows,
    compute_weekly_sentiment_score,
    format_kr_weekly_sentiment_report,
)


class TestKrWeeklySentiment(unittest.TestCase):
    def test_normalize_daily_rows_sorts_and_parses(self) -> None:
        payload = {
            "output2": [
                {"stck_bsop_date": "20260205", "futs_prpr": "334.10", "futs_trqu": "1000"},
                {"stck_bsop_date": "20260207", "futs_prpr": "338.40", "futs_trqu": "1,500"},
                {"stck_bsop_date": "20260206", "futs_prpr": "336.00", "futs_trqu": "1200"},
            ]
        }
        rows = _normalize_daily_rows(payload)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["date"], "20260207")
        self.assertAlmostEqual(rows[0]["close"], 338.4)
        self.assertAlmostEqual(rows[0]["volume"], 1500.0)

    def test_bullish_score(self) -> None:
        futures_rows = [
            {"date": "20260207", "close": 340.0, "volume": 1800},
            {"date": "20260206", "close": 338.0, "volume": 1500},
            {"date": "20260205", "close": 337.0, "volume": 1300},
            {"date": "20260204", "close": 334.0, "volume": 1200},
            {"date": "20260203", "close": 332.0, "volume": 1100},
        ]
        futures_features = _compute_futures_weekly_features(futures_rows, lookback_bars=5)
        options_features = _compute_options_features(
            {
                "output1": [{"total_bidp_rsqn": "2000", "otst_stpl_qty_icdc": "500"}],
                "output2": [{"total_bidp_rsqn": "1200", "otst_stpl_qty_icdc": "120"}],
            }
        )
        sentiment = compute_weekly_sentiment_score(
            futures_features=futures_features,
            options_features=options_features,
            basis_pct=0.45,
        )
        self.assertGreater(sentiment["score"], 0)
        self.assertIn(sentiment["regime"], {"bullish", "strong_bullish"})

    def test_bearish_score(self) -> None:
        futures_rows = [
            {"date": "20260207", "close": 323.0, "volume": 1900},
            {"date": "20260206", "close": 326.0, "volume": 1500},
            {"date": "20260205", "close": 328.0, "volume": 1300},
            {"date": "20260204", "close": 332.0, "volume": 1200},
            {"date": "20260203", "close": 335.0, "volume": 1100},
        ]
        futures_features = _compute_futures_weekly_features(futures_rows, lookback_bars=5)
        options_features = _compute_options_features(
            {
                "output1": [{"total_bidp_rsqn": "1100", "otst_stpl_qty_icdc": "90"}],
                "output2": [{"total_bidp_rsqn": "2600", "otst_stpl_qty_icdc": "800"}],
            }
        )
        sentiment = compute_weekly_sentiment_score(
            futures_features=futures_features,
            options_features=options_features,
            basis_pct=-0.6,
        )
        self.assertLess(sentiment["score"], 0)
        self.assertIn(sentiment["regime"], {"bearish", "strong_bearish"})

    def test_report_format_for_error(self) -> None:
        report = format_kr_weekly_sentiment_report(
            {"status": "error", "errors": ["선물 데이터 조회 실패"]}
        )
        self.assertIn("상태: 실패", report)
        self.assertIn("선물 데이터 조회 실패", report)


if __name__ == "__main__":
    unittest.main()
