from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.services.news import naver


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, list[Any]]:
        return {"items": []}


class _FakeAsyncClient:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._calls = calls

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self._calls.append({"url": url, **kwargs})
        return _FakeResponse()


class _FakeQuery:
    def filter(self, *args: object) -> "_FakeQuery":
        return self

    def all(self) -> list[Any]:
        return []


class _FakeDb:
    def query(self, *args: object) -> _FakeQuery:
        return _FakeQuery()

    def commit(self) -> None:
        return None


def _configure_quota(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    daily_limit: int = 100,
    monthly_limit: int = 1_000,
) -> None:
    monkeypatch.setattr(naver.settings, "naver_api_quota_state_path", str(tmp_path / "quota.json"))
    monkeypatch.setattr(naver.settings, "naver_api_daily_limit", daily_limit)
    monkeypatch.setattr(naver.settings, "naver_api_monthly_limit", monthly_limit)


@pytest.mark.asyncio
async def test_collect_naver_news_uses_api_hub_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    _configure_quota(monkeypatch, tmp_path)
    monkeypatch.setattr(naver.settings, "naver_api_client_id", "hub-client-id")
    monkeypatch.setattr(naver.settings, "naver_api_client_secret", "hub-client-secret")
    monkeypatch.setattr(naver.settings, "naver_api", "hub-api-key")
    monkeypatch.setattr(naver.httpx, "AsyncClient", lambda: _FakeAsyncClient(calls))

    count = await naver.collect_naver_news(_FakeDb(), "증시")

    assert count == 0
    assert len(calls) == 1
    assert calls[0]["url"] == "https://naverapihub.apigw.ntruss.com/search/v1/news"
    assert calls[0]["headers"] == {
        "X-NCP-APIGW-API-KEY-ID": "hub-client-id",
        "X-NCP-APIGW-API-KEY": "hub-client-secret",
    }
    assert calls[0]["params"]["query"] == "증시"


@pytest.mark.asyncio
async def test_collect_naver_news_skips_request_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(naver.settings, "naver_api_client_id", "hub-client-id")
    monkeypatch.setattr(naver.settings, "naver_api_client_secret", None)
    monkeypatch.setattr(naver.settings, "naver_api", None)

    def fail_if_called() -> None:
        raise AssertionError("API client must not be created without complete credentials")

    monkeypatch.setattr(naver.httpx, "AsyncClient", fail_if_called)

    count = await naver.collect_naver_news(_FakeDb(), "증시")

    assert count == 0


@pytest.mark.asyncio
async def test_collect_naver_news_supports_legacy_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    _configure_quota(monkeypatch, tmp_path)
    monkeypatch.setattr(naver.settings, "naver_api_client_id", "hub-client-id")
    monkeypatch.setattr(naver.settings, "naver_api_client_secret", None)
    monkeypatch.setattr(naver.settings, "naver_api", "legacy-api-key")
    monkeypatch.setattr(naver.httpx, "AsyncClient", lambda: _FakeAsyncClient(calls))

    count = await naver.collect_naver_news(_FakeDb(), "증시")

    assert count == 0
    assert calls[0]["headers"]["X-NCP-APIGW-API-KEY"] == "legacy-api-key"


@pytest.mark.asyncio
async def test_collect_naver_news_blocks_request_when_global_quota_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    _configure_quota(monkeypatch, tmp_path, daily_limit=1)
    monkeypatch.setattr(naver.settings, "naver_api_client_id", "hub-client-id")
    monkeypatch.setattr(naver.settings, "naver_api_client_secret", "hub-client-secret")
    monkeypatch.setattr(naver.httpx, "AsyncClient", lambda: _FakeAsyncClient(calls))

    first_count = await naver.collect_naver_news(_FakeDb(), "증시")
    blocked_count = await naver.collect_naver_news(_FakeDb(), "환율")

    assert first_count == 0
    assert blocked_count == 0
    assert len(calls) == 1
