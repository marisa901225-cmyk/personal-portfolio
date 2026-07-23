from __future__ import annotations

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


@pytest.mark.asyncio
async def test_collect_naver_news_uses_api_hub_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(naver.settings, "naver_api_client_id", "hub-client-id")
    monkeypatch.setattr(naver.settings, "naver_api", "hub-api-key")
    monkeypatch.setattr(naver.httpx, "AsyncClient", lambda: _FakeAsyncClient(calls))

    count = await naver.collect_naver_news(_FakeDb(), "증시")

    assert count == 0
    assert len(calls) == 1
    assert calls[0]["url"] == "https://naverapihub.apigw.ntruss.com/search/v1/news"
    assert calls[0]["headers"] == {
        "X-NCP-APIGW-API-KEY-ID": "hub-client-id",
        "X-NCP-APIGW-API-KEY": "hub-api-key",
    }
    assert calls[0]["params"]["query"] == "증시"


@pytest.mark.asyncio
async def test_collect_naver_news_skips_request_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(naver.settings, "naver_api_client_id", "hub-client-id")
    monkeypatch.setattr(naver.settings, "naver_api", None)

    def fail_if_called() -> None:
        raise AssertionError("API client must not be created without complete credentials")

    monkeypatch.setattr(naver.httpx, "AsyncClient", fail_if_called)

    count = await naver.collect_naver_news(_FakeDb(), "증시")

    assert count == 0
