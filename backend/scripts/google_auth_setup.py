
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv, set_key

# 프로젝트 루트 또는 현재 디렉토리의 .env 파일 로드
import sys
current_dir = os.getcwd()
env_path = os.path.join(current_dir, '.env')
if not os.path.exists(env_path):
    # 만약 backend 안에서 실행 중이면 상위 폴더도 확인
    env_path = os.path.join(current_dir, '..', '.env')

load_dotenv(env_path)
print(f"DEBUG: Using .env at {os.path.abspath(env_path)}") # 자기야, 어디서 읽는지 확인용이야!💖

def setup_google_auth():
    client_id = os.getenv("GOOGLE_DRIVE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ .env 파일에 GOOGLE_DRIVE_CLIENT_ID와 GOOGLE_DRIVE_CLIENT_SECRET을 먼저 넣어주세요, 자기야!💖")
        return

    # 클라이언트 정보 구성
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    # 스코프 설정 (드라이브 파일 업로드 권한)
    scopes = ['https://www.googleapis.com/auth/drive.file']

    try:
        # 로컬 서버를 띄워서 인증 진행 (자기가 말한 127.0.0.1 방식이야!)
        flow = InstalledAppFlow.from_client_config(client_config, scopes)
        creds = flow.run_local_server(port=0)

        # 리프레시 토큰 추출
        refresh_token = creds.refresh_token
        
        if refresh_token:
            # .env 파일에 저장
            set_key(env_path, "GOOGLE_DRIVE_REFRESH_TOKEN", refresh_token)
            print("✅ 우와! 리프레시 토큰을 성공적으로 가져와서 .env에 저장했어, 자기야!💖")
            print(f"Token: {refresh_token[:10]}...")
        else:
            print("❌ 리프레시 토큰이 안 나왔어... 이미 인증된 적이 있다면 구글 계정 설정에서 앱 권한을 삭제하고 다시 해봐!")

    except Exception as e:
        print(f"❌ 에러가 났어, 자기야: {e}")

if __name__ == "__main__":
    setup_google_auth()
