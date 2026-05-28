from __future__ import annotations

import os

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from backend.integrations.air_korea import air_korea_client as module


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, items: list[dict[str, str]]) -> None:
        self._items = items

    def json(self) -> dict:
        return {"response": {"body": {"items": self._items}}}


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse, calls: list[dict]) -> None:
        self._response = response
        self._calls = calls

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, *, params: dict, timeout: float) -> _FakeResponse:
        self._calls.append({"url": url, "params": params, "timeout": timeout})
        return self._response


@pytest.mark.asyncio
async def test_get_latest_active_alarm_ignores_cleared_recent_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    response = _FakeResponse(
        [
            {
                "districtName": "서울",
                "itemCode": "PM10",
                "issueGbn": "주의보",
                "issueDate": "2026-04-20",
                "issueTime": "21:00",
                "issueVal": "191",
                "clearDate": "2026-04-21",
                "clearTime": "15:00",
                "clearVal": "92",
            }
        ]
    )

    monkeypatch.setattr(module.settings, "kma_service_key", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda: _FakeAsyncClient(response, calls))

    result = await module.air_korea_client.get_latest_active_alarm(district_name="서울")

    assert result is None
    assert calls


@pytest.mark.asyncio
async def test_get_latest_active_alarm_returns_uncleared_alarm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []
    active_alarm = {
        "districtName": "서울",
        "itemCode": "PM25",
        "issueGbn": "주의보",
        "issueDate": "2026-05-28",
        "issueTime": "09:00",
        "issueVal": "80",
        "clearDate": "",
    }
    response = _FakeResponse([active_alarm])

    monkeypatch.setattr(module.settings, "kma_service_key", "test-key")
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda: _FakeAsyncClient(response, calls))

    result = await module.air_korea_client.get_latest_active_alarm(district_name="서울")

    assert result == active_alarm
