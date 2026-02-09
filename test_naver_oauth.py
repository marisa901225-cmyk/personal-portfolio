#!/usr/bin/env python3
"""
네이버 OAuth 라우터 기능 테스트

이 스크립트는 네이버 OAuth 관련 함수들이 올바르게 작동하는지 테스트합니다.
"""

import sys
import os

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

def test_jwt_token():
    """JWT 토큰 생성 및 검증 테스트"""
    from backend.core.auth import create_access_token
    from datetime import timedelta
    import jwt
    from backend.core.config import settings
    
    print("=" * 60)
    print("1. JWT 토큰 생성 테스트")
    print("=" * 60)
    
    test_data = {
        "naver_id": "test_user",
        "email": "test@example.com"
    }
    
    token = create_access_token(test_data, expires_delta=timedelta(minutes=30))
    print(f"✅ JWT 토큰 생성 성공")
    print(f"   토큰: {token[:50]}...")
    
    # 토큰 디코딩 검증
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        print(f"✅ JWT 토큰 검증 성공")
        print(f"   Payload: {payload}")
    except Exception as e:
        print(f"❌ JWT 토큰 검증 실패: {e}")
        sys.exit(1)
    
    print()


def test_naver_login_url():
    """네이버 로그인 URL 생성 테스트"""
    print("=" * 60)
    print("2. 네이버 로그인 URL 생성 테스트")
    print("=" * 60)
    
    import asyncio
    from backend.routers.naver_auth import get_naver_login_url
    
    async def run_test():
        result = await get_naver_login_url()
        print(f"✅ 네이버 로그인 URL 생성 성공")
        print(f"   URL: {result.auth_url}")
        print(f"   State: {result.state}")
        return result
    
    result = asyncio.run(run_test())
    print()
    return result


def test_config():
    """설정 로드 테스트"""
    print("=" * 60)
    print("0. 설정 로드 테스트")
    print("=" * 60)
    
    from backend.core.config import settings
    
    print(f"✅ 설정 로드 성공")
    print(f"   JWT Secret Key: {settings.jwt_secret_key[:20]}...")
    print(f"   JWT Algorithm: {settings.jwt_algorithm}")
    print(f"   Naver Client ID: {settings.naver_client_id}")
    print(f"   Naver Redirect URI: {settings.naver_redirect_uri}")
    print(f"   Naver Allowed IDs: {settings.naver_allowed_ids}")
    print()


if __name__ == "__main__":
    print("\n🧪 네이버 OAuth 라우터 기능 테스트 시작\n")
    
    try:
        test_config()
        test_jwt_token()
        test_naver_login_url()
        
        print("=" * 60)
        print("✅ 모든 테스트 통과!")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
