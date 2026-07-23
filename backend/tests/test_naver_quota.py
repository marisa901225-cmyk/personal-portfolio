from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.services.news.naver_quota import NaverQuotaStateError, reserve_naver_api_call


KST = ZoneInfo("Asia/Seoul")


def test_quota_blocks_before_daily_limit_is_exceeded(tmp_path) -> None:
    state_path = tmp_path / "naver_quota.json"
    now = datetime(2026, 7, 23, 10, 0, tzinfo=KST)

    first = reserve_naver_api_call(
        state_path=state_path,
        daily_limit=2,
        monthly_limit=10,
        now=now,
    )
    second = reserve_naver_api_call(
        state_path=state_path,
        daily_limit=2,
        monthly_limit=10,
        now=now,
    )
    blocked = reserve_naver_api_call(
        state_path=state_path,
        daily_limit=2,
        monthly_limit=10,
        now=now,
    )

    assert first.allowed is True
    assert second.allowed is True
    assert blocked.allowed is False
    assert blocked.daily_used == 2
    assert blocked.monthly_used == 2


def test_quota_resets_daily_count_but_preserves_monthly_count(tmp_path) -> None:
    state_path = tmp_path / "naver_quota.json"
    reserve_naver_api_call(
        state_path=state_path,
        daily_limit=10,
        monthly_limit=2,
        now=datetime(2026, 7, 23, 23, 59, tzinfo=KST),
    )
    next_day = reserve_naver_api_call(
        state_path=state_path,
        daily_limit=10,
        monthly_limit=2,
        now=datetime(2026, 7, 24, 0, 0, tzinfo=KST),
    )
    blocked = reserve_naver_api_call(
        state_path=state_path,
        daily_limit=10,
        monthly_limit=2,
        now=datetime(2026, 7, 24, 0, 1, tzinfo=KST),
    )

    assert next_day.allowed is True
    assert next_day.daily_used == 1
    assert next_day.monthly_used == 2
    assert blocked.allowed is False


def test_quota_resets_both_counts_in_new_month(tmp_path) -> None:
    state_path = tmp_path / "naver_quota.json"
    reserve_naver_api_call(
        state_path=state_path,
        daily_limit=1,
        monthly_limit=1,
        now=datetime(2026, 7, 31, 23, 59, tzinfo=KST),
    )

    new_month = reserve_naver_api_call(
        state_path=state_path,
        daily_limit=1,
        monthly_limit=1,
        now=datetime(2026, 8, 1, 0, 0, tzinfo=KST),
    )

    assert new_month.allowed is True
    assert new_month.daily_used == 1
    assert new_month.monthly_used == 1


def test_quota_fails_closed_when_state_is_corrupt(tmp_path) -> None:
    state_path = tmp_path / "naver_quota.json"
    state_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(NaverQuotaStateError):
        reserve_naver_api_call(
            state_path=state_path,
            daily_limit=10,
            monthly_limit=100,
        )


def test_quota_serializes_concurrent_reservations(tmp_path) -> None:
    state_path = tmp_path / "naver_quota.json"
    now = datetime(2026, 7, 23, 10, 0, tzinfo=KST)

    def reserve_once() -> bool:
        return reserve_naver_api_call(
            state_path=state_path,
            daily_limit=10,
            monthly_limit=100,
            now=now,
        ).allowed

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: reserve_once(), range(40)))

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert sum(results) == 10
    assert payload["daily_used"] == 10
    assert payload["monthly_used"] == 10
