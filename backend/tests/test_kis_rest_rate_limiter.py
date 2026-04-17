from __future__ import annotations

import json
import os
from unittest.mock import patch

def _load_module():
    from backend.integrations.kis import rest_rate_limiter

    return rest_rate_limiter


def test_rate_limit_env_overrides_are_respected():
    module = _load_module()
    with patch.dict(
        os.environ,
        {
            "KIS_REST_RATE_LIMIT_PER_SEC": "3",
            "KIS_REST_RATE_WINDOW_SEC": "1.5",
        },
        clear=False,
    ):
        assert module.get_rest_rate_limit_per_sec() == 3
        assert module.get_rest_rate_window_sec() == 1.5


def test_throttle_rest_requests_waits_once_limit_is_reached(tmp_path):
    module = _load_module()
    now = {"value": 0.0}
    sleep_calls: list[float] = []

    def fake_clock() -> float:
        return now["value"]

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        now["value"] += seconds

    for _ in range(3):
        module.throttle_rest_requests(
            limit_per_sec=3,
            window_sec=1.0,
            config_dir=tmp_path,
            clock=fake_clock,
            sleeper=fake_sleep,
        )

    assert sleep_calls == []

    module.throttle_rest_requests(
        limit_per_sec=3,
        window_sec=1.0,
        config_dir=tmp_path,
        clock=fake_clock,
        sleeper=fake_sleep,
    )

    assert len(sleep_calls) == 1
    assert sleep_calls[0] >= 0.999

    payload = json.loads((tmp_path / "KIS.rest_rate.json").read_text(encoding="utf-8"))
    timestamps = payload["timestamps"]
    assert len(timestamps) == 1
    assert timestamps[0] >= 1.0


def test_throttle_rest_min_gap_waits_until_spacing_is_met(tmp_path):
    module = _load_module()
    now = {"value": 0.0}
    sleep_calls: list[float] = []

    def fake_clock() -> float:
        return now["value"]

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        now["value"] += seconds

    module.throttle_rest_min_gap(
        scope="daily-bars",
        min_gap_sec=0.12,
        config_dir=tmp_path,
        clock=fake_clock,
        sleeper=fake_sleep,
    )
    module.throttle_rest_min_gap(
        scope="daily-bars",
        min_gap_sec=0.12,
        config_dir=tmp_path,
        clock=fake_clock,
        sleeper=fake_sleep,
    )

    assert len(sleep_calls) == 1
    assert sleep_calls[0] >= 0.119
