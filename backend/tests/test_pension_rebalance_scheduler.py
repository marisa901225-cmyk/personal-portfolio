from __future__ import annotations

from datetime import datetime

import backend.scripts.run_pension_rebalance_scheduler as scheduler
from backend.scripts.run_pension_rebalance_scheduler import (
    _is_quarter_window,
    _is_scheduled_trading_day,
    _open_day_from_holiday_rows,
    _quarter_key,
)


def test_quarter_window_uses_quarter_end_month_last_seven_days(monkeypatch) -> None:
    monkeypatch.delenv("PENSION_REBALANCE_QUARTER_WINDOW_DAYS", raising=False)

    assert not _is_quarter_window(datetime(2026, 4, 1, 10, 5))
    assert not _is_quarter_window(datetime(2026, 3, 24, 10, 5))
    assert _is_quarter_window(datetime(2026, 3, 25, 10, 5))
    assert _is_quarter_window(datetime(2026, 3, 31, 10, 5))


def test_quarter_window_days_can_be_configured(monkeypatch) -> None:
    monkeypatch.setenv("PENSION_REBALANCE_QUARTER_WINDOW_DAYS", "3")

    assert not _is_quarter_window(datetime(2026, 6, 27, 10, 5))
    assert _is_quarter_window(datetime(2026, 6, 28, 10, 5))
    assert _is_quarter_window(datetime(2026, 6, 30, 10, 5))


def test_quarter_key_matches_quarter_end_month() -> None:
    assert _quarter_key(datetime(2026, 3, 31, 10, 5)) == "2026Q1"
    assert _quarter_key(datetime(2026, 6, 30, 10, 5)) == "2026Q2"


def test_open_day_from_holiday_rows_uses_kis_open_flag() -> None:
    rows = [
        {"bass_dt": "20260330", "opnd_yn": "Y"},
        {"bass_dt": "20260331", "opnd_yn": "N"},
    ]

    assert _open_day_from_holiday_rows("20260330", rows) is True
    assert _open_day_from_holiday_rows("20260331", rows) is False
    assert _open_day_from_holiday_rows("20260401", rows) is None


def test_scheduled_trading_day_uses_kis_holiday_lookup(monkeypatch) -> None:
    called: list[str] = []

    def fake_query(date_key: str) -> bool:
        called.append(date_key)
        return date_key == "20260330"

    monkeypatch.setattr(scheduler, "_query_kis_trading_day", fake_query)

    assert _is_scheduled_trading_day(datetime(2026, 3, 30, 10, 5))
    assert not _is_scheduled_trading_day(datetime(2026, 3, 31, 10, 5))
    assert called == ["20260330", "20260331"]


def test_scheduled_trading_day_skips_weekend_without_kis_lookup(monkeypatch) -> None:
    def fake_query(date_key: str) -> bool:
        raise AssertionError("weekends should be skipped before KIS lookup")

    monkeypatch.setattr(scheduler, "_query_kis_trading_day", fake_query)

    assert not _is_scheduled_trading_day(datetime(2026, 3, 29, 10, 5))
