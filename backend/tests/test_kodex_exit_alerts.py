import unittest

import pandas as pd

from backend.services.kodex_exit_alerts import (
    KodexExitAlertConfig,
    _is_last_trading_day_of_week,
    evaluate_daily_warning,
    evaluate_weekly_confirmation,
)


def _daily_frame() -> pd.DataFrame:
    rows = []
    base_dates = pd.bdate_range("2026-01-05", periods=80)
    price = 100.0
    for idx, dt in enumerate(base_dates):
        if idx < 70:
            price += 0.35
        elif idx < 76:
            price += 0.9
        else:
            price -= 1.4
        rows.append(
            {
                "date": dt.strftime("%Y%m%d"),
                "open": round(price - 0.3, 2),
                "high": round(price + 0.7, 2),
                "low": round(price - 0.8, 2),
                "close": round(price, 2),
                "volume": 100000,
            }
        )
    return pd.DataFrame(rows)


class _FakeApi:
    def __init__(self, trading_days: set[str]) -> None:
        self.trading_days = trading_days

    def is_trading_day(self, date: str) -> bool:
        return date in self.trading_days


class KodexExitAlertsTests(unittest.TestCase):
    def test_daily_warning_triggers_after_recent_high_retrace(self):
        bars = _daily_frame()
        today = str(bars.iloc[-1]["date"])
        quote = {
            "price": 120.0,
            "open": 121.0,
            "high": 123.5,
            "low": 119.5,
            "volume": 120000,
        }
        config = KodexExitAlertConfig(
            daily_high_lookback=20,
            daily_peak_fresh_bars=7,
            daily_retrace_pct=2.0,
            daily_ma_period=5,
        )

        result = evaluate_daily_warning(bars, quote, today=today, config=config)

        self.assertIsNotNone(result)
        self.assertTrue(result["triggered"])
        self.assertLess(result["retrace_pct"], -2.0)
        self.assertLess(result["current_price"], result["ma_value"])

    def test_weekly_confirmation_uses_weekly_and_monthly_filters(self):
        bars = _daily_frame()
        today = str(bars.iloc[-1]["date"])
        quote = {
            "price": 119.0,
            "open": 120.5,
            "high": 121.0,
            "low": 118.5,
            "volume": 150000,
        }
        config = KodexExitAlertConfig(
            weekly_high_lookback=8,
            weekly_retrace_pct=3.0,
            weekly_ma_period=4,
            monthly_ma_period=3,
        )

        result = evaluate_weekly_confirmation(bars, quote, today=today, config=config)

        self.assertIsNotNone(result)
        self.assertTrue(result["triggered"])
        self.assertLess(result["retrace_pct"], -3.0)
        self.assertLess(result["weekly_close"], result["weekly_ma"])

    def test_last_trading_day_of_week_handles_friday_holiday(self):
        api = _FakeApi(
            {
                "20260420",  # Mon
                "20260421",
                "20260422",
                "20260423",  # Thu
            }
        )

        self.assertTrue(_is_last_trading_day_of_week(api, "20260423"))
        self.assertFalse(_is_last_trading_day_of_week(api, "20260422"))


if __name__ == "__main__":
    unittest.main()
