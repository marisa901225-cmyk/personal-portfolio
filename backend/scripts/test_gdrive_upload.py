#!/usr/bin/env python3
"""
구글 드라이브 업로드 테스트 스크립트
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드
env_path = Path.home() / "ai-models" / "myasset.env"
load_dotenv(env_path)

# 백엔드 모듈 임포트를 위해 경로 추가
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root.parent))

from backend.services.google_drive_client import GoogleDriveService

def main():
    print("🚀 구글 드라이브 업로드 테스트 시작!")
    
    # 환경변수 확인
    client_id = os.getenv("GOOGLE_DRIVE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET")
    refresh_token = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN")
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    
    if not client_id or not client_secret or not refresh_token:
        print("❌ 구글 드라이브 환경변수가 설정되지 않았어요!")
        return False
    
    print(f"✅ Client ID: {client_id[:20]}...")
    print(f"✅ Refresh Token: {refresh_token[:20]}...")
    
    # 액세스 토큰 발급
    print("\n🔑 액세스 토큰 발급 중...")
    access_token = GoogleDriveService.get_access_token(client_id, client_secret, refresh_token)
    
    if not access_token:
        print("❌ 액세스 토큰 발급 실패!")
        return False
    
    print(f"✅ 액세스 토큰 발급 성공: {access_token[:20]}...")
    
    # 폴더 확인/생성
    if not folder_id:
        folder_name = "portfolio-backups"
        print(f"\n📁 폴더 '{folder_name}' 찾는 중...")
        folder_id = GoogleDriveService.get_folder_id_by_name(folder_name, access_token)
        
        if not folder_id:
            print(f"📁 폴더 생성 중...")
            folder_id = GoogleDriveService.create_folder(folder_name, access_token)
            print(f"✅ 폴더 생성 완료: {folder_id}")
        else:
            print(f"✅ 폴더 찾음: {folder_id}")
    
    # 테스트 파일 업로드
    test_file = backend_root / "test_upload.txt"
    print(f"\n📤 파일 업로드 중: {test_file}")
    
    success = GoogleDriveService.upload_file(str(test_file), folder_id, access_token)
    
    if success:
        print("✅ 업로드 성공! 💖")
        print("구글 드라이브에서 확인해보세요!")
        return True
    else:
        print("❌ 업로드 실패!")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
