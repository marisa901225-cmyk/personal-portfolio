from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from backend.routers import naver_auth


@pytest.mark.asyncio
async def test_naver_callback_rejects_unknown_state_before_token_exchange() -> None:
    naver_auth._state_store.clear()
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/api/auth/naver/callback",
            "raw_path": b"/api/auth/naver/callback",
            "query_string": b"",
            "headers": [],
            "client": ("203.0.113.10", 12345),
            "server": ("testserver", 443),
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        await naver_auth.naver_callback(
            request=request,
            response=Response(),
            code="oauth-code",
            state="unknown-state",
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired OAuth state"
