from __future__ import annotations

import os

from fastapi import Header, HTTPException

API_TOKEN = os.getenv("API_TOKEN")


async def verify_api_token(x_api_token: str | None = Header(default=None)) -> None:
    """
    간단한 토큰 기반 인증.
    - 환경변수 API_TOKEN 이 설정되어 있지 않으면 인증을 강제하지 않는다.
    - 설정되어 있다면, 요청 헤더 X-API-Token 과 동일해야 통과.
    """
    if not API_TOKEN:
        return
    if not x_api_token or x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid api token")

