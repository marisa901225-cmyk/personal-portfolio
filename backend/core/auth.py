from __future__ import annotations
from fastapi import Header, HTTPException, Depends, Cookie, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .config import settings
from datetime import datetime, timedelta, timezone
from typing import Any

import hmac
import ipaddress
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


def _tailnet_domain() -> str:
    return str(os.getenv("TAILSCALE_TAILNET_DOMAIN", "tail5c2348.ts.net") or "").strip().lower()


def _is_tailscale_ip(hostname: str) -> bool:
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10")


def _is_tailnet_or_local_host(request: Request) -> bool:
    forwarded_host = str(request.headers.get("x-forwarded-host") or "").strip()
    host = forwarded_host or request.headers.get("host") or request.url.hostname or ""
    hostname = str(host).split(",", 1)[0].strip().split(":", 1)[0].strip().lower()
    if not hostname:
        return False
    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return True

    tailnet_domain = _tailnet_domain()
    if tailnet_domain and (hostname == tailnet_domain or hostname.endswith(f".{tailnet_domain}")):
        return True

    return _is_tailscale_ip(hostname)


async def verify_api_token(
    request: Request,
    x_api_token: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    auth_token: str | None = Cookie(default=None, alias="auth_token"),
) -> None:
    """
    통합 인증 로직.
    1. Tailnet/localhost 접근: JWT 또는 X-API-Token 중 하나면 통과.
    2. 그 외 호스트 접근: JWT와 X-API-Token 둘 다 유효해야 통과.
    """
    # 1. JWT 검증 시도
    token = auth_token
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
    
    jwt_valid = False
    if token:
        try:
            jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )
            # JWT 검증 성공
            jwt_valid = True
        except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
            # JWT 실패 시 로그를 남기거나 조용히 넘어가서 API 키를 확인하게 함
            pass

    # 2. 기존 API 키 검사
    token_required = resolve_api_token()
    
    # 설정이 없는 경우 (디버그 모드나 무인증 허용 시)
    if not token_required:
        if settings.debug or ALLOW_NO_AUTH:
            return
        raise HTTPException(status_code=503, detail="API token not configured")
    
    # X-API-Token 헤더 확인
    api_key_valid = bool(x_api_token and hmac.compare_digest(x_api_token, token_required))
    tailnet_or_local = _is_tailnet_or_local_host(request)

    if tailnet_or_local and (jwt_valid or api_key_valid):
        return

    if (not tailnet_or_local) and jwt_valid and api_key_valid:
        return

    raise HTTPException(
        status_code=401,
        detail=(
            "Invalid authentication credentials (JWT or API Key required)"
            if tailnet_or_local
            else "Invalid authentication credentials (JWT and API Key required)"
        ),
    )


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
