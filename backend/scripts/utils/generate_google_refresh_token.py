import os
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from dotenv import load_dotenv

# 프로젝트 루트를 패스에 추가
repo_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(repo_root))

from backend.core.env_paths import get_project_env_files, get_secrets_env_file


def generate_refresh_token():
    for env_path in get_project_env_files():
        load_dotenv(env_path, override=True)

    client_id = os.getenv("GOOGLE_DRIVE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("❌ .env 파일에 GOOGLE_DRIVE_CLIENT_ID와 GOOGLE_DRIVE_CLIENT_SECRET이 설정되어 있어야 합니다!")
        return

    # 구글 드라이브 업로드 권한 스코프
    SCOPES = ['https://www.googleapis.com/auth/drive.file']

    # 클라이언트 정보 설정
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    # Flow 실행 (prompt='consent'를 추가하여 항상 refresh token을 받도록 설정)
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    
    # 로컬 서버를 띄울 수 없는 환경을 위해 console 기반 인증 사용 가능 여부 확인
    # 최근 버전은 로컬 서버가 기본이므로, URL을 출력하고 유저가 브라우저에서 작업하도록 함
    print("\n" + "="*60)
    print("🔑 Google Drive Production Refresh Token 발급 프로세스 시작!💖")
    print("="*60)
    print("\n1. 아래 출력되는 URL을 복사해서 브라우저(로그인된 창)에 붙여넣으세요.")
    print("2. 'Production' 전환 후 처음이라면 '이 앱은 Google에서 확인하지 않았습니다'가 뜰 수 있어요.")
    print("3. '고급' -> '[앱이름](으)로 이동'을 클릭해서 권한을 승인해주세요.")
    print("4. 승인 후 리다이렉트된 페이지에서 인증 코드를 복사해오세요.")
    print("="*60 + "\n")

    # run_local_server는 브라우저를 직접 띄우려고 시도함. 
    # ssh 환경 등을 고려해 URL만 출력하고 대기하도록 함.
    try:
        creds = flow.run_local_server(
            port=0,
            prompt='consent',
            access_type='offline',
            include_granted_scopes='true'
        )
        
        print("\n" + "✨"*20)
        print("✅ 인증 성공! 새로운 Refresh Token입니다:")
        print(f"\n👉 {creds.refresh_token}\n")
        print(f"이 토큰을 {get_secrets_env_file()}의 GOOGLE_DRIVE_REFRESH_TOKEN 항목에 업데이트하세요!💖")
        print("✨"*20 + "\n")
        
    except Exception as e:
        print(f"\n❌ 인증 도중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    generate_refresh_token()
