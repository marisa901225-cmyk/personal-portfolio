import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add project root to sys.path (personal-portfolio/)
# tests/conftest.py -> backend/ -> personal-portfolio/
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env file from backend directory
BACKEND_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
    print(f"DEBUG: Loaded .env from {ENV_PATH}")

# Ensure DATABASE_URL is set to test DB
TEST_DB_PATH = "/home/dlckdgn/personal-portfolio/devplan/test_db/test.db"

# 디렉토리 생성 보장
os.makedirs(os.path.dirname(TEST_DB_PATH), exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

# Override with test environment variables (must override after loading .env)
# This ensures test values take precedence over production .env values
os.environ["API_TOKEN"] = "test-token"
os.environ["TELEGRAM_CHAT_ID"] = "123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-only-do-not-use-in-production")
os.environ.setdefault("NAVER_CLIENT_ID", "test-naver-client-id")
os.environ.setdefault("NAVER_CLIENT_SECRET", "test-naver-client-secret")

print(f"DEBUG: Using DATABASE_URL={os.environ['DATABASE_URL']}")
print(f"DEBUG: API_TOKEN={'***' if os.environ.get('API_TOKEN') else 'NOT SET'}")
