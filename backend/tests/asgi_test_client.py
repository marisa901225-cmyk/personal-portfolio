from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient, Response


async def asgi_request(app: Any, method: str, url: str, **kwargs: Any) -> Response:
    async def run_sync_inline(func: Any, *args: Any, **options: Any) -> Any:
        del options
        return func(*args)

    with patch("anyio.to_thread.run_sync", new=run_sync_inline):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, url, **kwargs)


class ASGITestClient:
    def __init__(self, app: Any) -> None:
        self.app = app

    def get(self, url: str, **kwargs: Any) -> Response:
        return asyncio.run(asgi_request(self.app, "GET", url, **kwargs))

    def post(self, url: str, **kwargs: Any) -> Response:
        return asyncio.run(asgi_request(self.app, "POST", url, **kwargs))

    def delete(self, url: str, **kwargs: Any) -> Response:
        return asyncio.run(asgi_request(self.app, "DELETE", url, **kwargs))
