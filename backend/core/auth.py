from __future__ import annotations
from fastapi import Header, HTTPException
from .config import settings

import hmac
import os

API_TOKEN = settings.api_token
ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").lower() in ("1", "true", "yes")


def resolve_api_token() -> str | None:
    """
    API_TOKEN이 수동으로 변경되지 않았다면 설정된 값을 반환한다.
    """
    return API_TOKEN


async def verify_api_token(x_api_token: str | None = Header(default=None)) -> None:
    """
    간단한 토큰 기반 인증.
    - 환경변수 API_TOKEN 이 설정되어 있지 않으면 기본적으로 차단한다.
    - debug 또는 ALLOW_NO_AUTH=1/true/yes 인 경우만 인증을 생략한다.
    - 설정되어 있다면, 요청 헤더 X-API-Token 과 동일해야 통과.
    """
    token = resolve_api_token()
    if not token:
        if settings.debug or ALLOW_NO_AUTH:
            return
        raise HTTPException(status_code=503, detail="API token not configured")
    if not x_api_token or not hmac.compare_digest(x_api_token, token):
        raise HTTPException(status_code=401, detail="invalid api token")
