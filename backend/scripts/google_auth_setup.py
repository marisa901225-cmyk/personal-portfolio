
import os
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv, set_key

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root.parent))

from backend.core.env_paths import get_secrets_env_file

env_path = get_secrets_env_file()
load_dotenv(env_path, override=True)
print(f"DEBUG: Using secrets env at {env_path.resolve()}")

def setup_google_auth():
    client_id = os.getenv("GOOGLE_DRIVE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ secrets env 파일에 GOOGLE_DRIVE_CLIENT_ID와 GOOGLE_DRIVE_CLIENT_SECRET을 먼저 넣어주세요, 자기야!💖")
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
            # secrets env 파일에 저장
            env_path.parent.mkdir(parents=True, exist_ok=True)
            set_key(str(env_path), "GOOGLE_DRIVE_REFRESH_TOKEN", refresh_token)
            print("✅ 우와! 리프레시 토큰을 성공적으로 가져와서 secrets env에 저장했어, 자기야!💖")
        else:
            print("❌ 리프레시 토큰이 안 나왔어... 이미 인증된 적이 있다면 구글 계정 설정에서 앱 권한을 삭제하고 다시 해봐!")

    except Exception as e:
        print(f"❌ 에러가 났어, 자기야: {e}")

if __name__ == "__main__":
    setup_google_auth()
