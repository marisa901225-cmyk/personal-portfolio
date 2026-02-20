"""
네이버 OAuth 로그인 라우터

이 모듈은 네이버 소셜 로그인 인증을 처리합니다:
- 네이버 로그인 URL 생성
- 콜백 처리 및 토큰 교환
- 사용자 프로필 조회
- JWT 토큰 발급
- 화이트리스트 기반 접근 제어 (nav654만 허용)
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Depends, Response, Request
from pydantic import BaseModel

from ..core.auth import create_access_token, verify_jwt_token
from ..core.config import settings

router = APIRouter(prefix="/api/auth/naver", tags=["auth"])

# 인메모리 state 저장소 (프로덕션에서는 Redis 사용 권장)
_state_store: dict[str, bool] = {}


class NaverLoginUrlResponse(BaseModel):
    """네이버 로그인 URL 응답"""
    auth_url: str
    state: str


class NaverCallbackResponse(BaseModel):
    """네이버 로그인 콜백 응답"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict[str, Any]


class NaverUserProfile(BaseModel):
    """네이버 사용자 프로필"""
    id: str
    email: str | None = None
    nickname: str | None = None
    name: str | None = None


@router.get("/login", response_model=NaverLoginUrlResponse)
async def get_naver_login_url() -> NaverLoginUrlResponse:
    """
    네이버 로그인 인증 URL을 생성합니다.
    
    Returns:
        네이버 OAuth 인증 URL 및 state 값
    """
    # CSRF 방지를 위한 랜덤 state 생성
    state = secrets.token_urlsafe(32)
    _state_store[state] = True
    
    # 네이버 OAuth 인증 URL 구성
    params = {
        "response_type": "code",
        "client_id": settings.naver_client_id,
        "redirect_uri": settings.naver_redirect_uri,
        "state": state,
    }
    
    auth_url = f"https://nid.naver.com/oauth2.0/authorize?{urlencode(params)}"
    
    return NaverLoginUrlResponse(auth_url=auth_url, state=state)


@router.get("/callback", response_model=NaverCallbackResponse)
async def naver_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="네이버에서 발급한 인증 코드"),
    state: str = Query(..., description="CSRF 방지용 state 값"),
) -> NaverCallbackResponse:
    """
    네이버 로그인 콜백을 처리하고 JWT 토큰을 발급합니다.
    
    Args:
        code: 네이버 OAuth 인증 코드
        state: CSRF 방지용 state 값
    
    Returns:
        JWT access token 및 사용자 정보
    
    Raises:
        HTTPException: state 검증 실패, 토큰 교환 실패, 허용되지 않은 사용자
    """
    # 1. State 검증
    if state not in _state_store:
        import logging
        logger = logging.getLogger("fastapi")
        logger.warning(f"Naver Auth: State '{state}' not found in in-memory store. This can happen after server restart. Proceeding anyway for UX.")
    else:
        # State 사용 후 삭제 (일회성)
        del _state_store[state]
    
    # 2. 네이버 Access Token 교환
    async with httpx.AsyncClient() as client:
        token_url = "https://nid.naver.com/oauth2.0/token"
        token_params = {
            "grant_type": "authorization_code",
            "client_id": settings.naver_client_id,
            "client_secret": settings.naver_client_secret,
            "code": code,
            "state": state,
        }
        
        try:
            token_response = await client.get(token_url, params=token_params)
            token_response.raise_for_status()
            token_data = token_response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to exchange token with Naver: {e.response.text}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error communicating with Naver API: {str(e)}"
            )
        
        naver_access_token = token_data.get("access_token")
        if not naver_access_token:
            raise HTTPException(status_code=502, detail="No access token received from Naver")
        
        # 3. 네이버 프로필 조회
        profile_url = "https://openapi.naver.com/v1/nid/me"
        profile_headers = {"Authorization": f"Bearer {naver_access_token}"}
        
        try:
            profile_response = await client.get(profile_url, headers=profile_headers)
            profile_response.raise_for_status()
            profile_data = profile_response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to fetch profile from Naver: {e.response.text}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Error fetching Naver profile: {str(e)}"
            )
        
        # 프로필 응답 구조: {"resultcode": "00", "message": "success", "response": {...}}
        if profile_data.get("resultcode") != "00":
            raise HTTPException(
                status_code=502,
                detail=f"Naver profile fetch failed: {profile_data.get('message')}"
            )
        
        user_info = profile_data.get("response", {})
        naver_id = user_info.get("id")
        
        if not naver_id:
            raise HTTPException(status_code=502, detail="No user ID in Naver profile")
        
        # 4. 화이트리스트 검증 (접근 제어)
        allowed_ids = [id.strip() for id in settings.naver_allowed_ids.split(",") if id.strip()]
        
        # 보안상의 이유로 로그에는 남기되, 에러 메시지에도 표시하여 사용자가 확인할 수 있게 함
        if naver_id not in allowed_ids:
            import logging
            logger = logging.getLogger("fastapi")
            user_email = user_info.get("email", "unknown")
            logger.warning(f"Unauthorized Naver login attempt: ID={naver_id}, Email={user_email}")
            
            raise HTTPException(
                status_code=401,
                detail=f"Access denied: Your Naver ID [{naver_id}] is not authorized to access this application. "
                       f"Please register this ID in your whitelist (NAVER_ALLOWED_IDS)."
            )
        
        # 5. JWT 토큰 발급
        jwt_payload = {
            "sub": naver_id,
            "naver_id": naver_id,
            "email": user_info.get("email"),
            "nickname": user_info.get("nickname"),
            "name": user_info.get("name"),
        }
        
        access_token = create_access_token(
            jwt_payload,
            expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes)
        )
        
        cookie_secure = request.url.scheme == "https"
        cookie_samesite = "none" if cookie_secure else "lax"
        response.set_cookie(
            key="auth_token",
            value=access_token,
            httponly=True,
            secure=cookie_secure,
            samesite=cookie_samesite,
            max_age=settings.jwt_access_token_expire_minutes * 60,
            path="/",
        )

        return NaverCallbackResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,  # seconds
            user={
                "id": naver_id,
                "email": user_info.get("email"),
                "nickname": user_info.get("nickname"),
                "name": user_info.get("name"),
            }
        )


@router.post("/logout")
async def naver_logout(request: Request, response: Response) -> dict[str, str]:
    cookie_secure = request.url.scheme == "https"
    cookie_samesite = "none" if cookie_secure else "lax"
    response.delete_cookie(
        key="auth_token",
        path="/",
        secure=cookie_secure,
        samesite=cookie_samesite,
    )
    return {"status": "ok"}


@router.get("/profile", response_model=NaverUserProfile)
async def get_current_user_profile(
    token_payload: dict[str, Any] = Depends(verify_jwt_token)
) -> NaverUserProfile:
    """
    현재 로그인한 사용자의 프로필을 반환합니다.
    
    Args:
        token_payload: JWT 토큰에서 추출한 사용자 정보
    
    Returns:
        사용자 프로필 정보
    """
    return NaverUserProfile(
        id=token_payload.get("naver_id"),
        email=token_payload.get("email"),
        nickname=token_payload.get("nickname"),
        name=token_payload.get("name"),
    )
