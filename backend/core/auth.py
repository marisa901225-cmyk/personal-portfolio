from __future__ import annotations
from fastapi import Header, HTTPException, Depends, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import settings
from datetime import datetime, timedelta, timezone
from typing import Any

import hmac
import os
import jwt

API_TOKEN = settings.api_token
ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").lower() in ("1", "true", "yes")

# HTTPBearer security scheme for JWT
security = HTTPBearer(auto_error=False)


def resolve_api_token() -> str | None:
    """
    API_TOKEN이 수동으로 변경되지 않았다면 설정된 값을 반환한다.
    """
    return API_TOKEN


async def verify_api_token(
    x_api_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    auth_token: str | None = Cookie(default=None, alias="auth_token"),
) -> None:
    """
    통합 인증 로직.
    1. Authorization 헤더가 있으면 JWT 검증 시도.
    2. JWT가 성공하면 API 키 검사 없이 통과.
    3. JWT가 없거나 실패하면 기존 X-API-Token (API 키) 검사.
    """
    # 1. JWT 검증 시도 (Cookie or Authorization: Bearer <TOKEN>)
    token = auth_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    if token:
        try:
            jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )
            # JWT 검증 성공 시 API 키 검사 우회
            return
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            # JWT 실패 시 API 키 검사로 넘어가거나 에러 발생
            if not x_api_token:
                raise HTTPException(status_code=401, detail="Invalid token and no API key provided")

    # 2. 기존 API 키 검사
    token = resolve_api_token()
    if not token:
        if settings.debug or ALLOW_NO_AUTH:
            return
        raise HTTPException(status_code=503, detail="API token not configured")
    
    if not x_api_token or not hmac.compare_digest(x_api_token, token):
        raise HTTPException(status_code=401, detail="invalid api token")


# ============================================
# JWT 인증 함수
# ============================================

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """
    JWT access token을 생성합니다.
    
    Args:
        data: 토큰에 포함할 데이터 (예: {"naver_id": "nav654", "email": "..."})
        expires_delta: 토큰 만료 시간 (기본값: settings.jwt_access_token_expire_minutes)
    
    Returns:
        생성된 JWT 토큰 문자열
    """
    to_encode = data.copy()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


async def verify_jwt_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    auth_token: str | None = Cookie(default=None, alias="auth_token"),
) -> dict[str, Any]:
    """
    JWT 토큰을 검증하고 페이로드를 반환합니다.
    
    Args:
        credentials: HTTPBearer에서 추출한 인증 정보
    
    Returns:
        토큰 페이로드 (dict)
    
    Raises:
        HTTPException: 토큰이 만료되었거나 유효하지 않은 경우
    """
    try:
        token = auth_token or (credentials.credentials if credentials else None)
        if not token:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"}
            )
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )
