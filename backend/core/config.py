from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.core.env_paths import get_project_env_file_strings

# 프로젝트 루트 디렉토리 설정
BASE_DIR = Path(__file__).resolve().parents[1]
STORAGE_DIR = BASE_DIR / "storage"
DB_DIR = STORAGE_DIR / "db"

def _get_default_db_url() -> str:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db_path = DB_DIR / "portfolio.db"
    return f"sqlite:///{db_path.as_posix()}"

class Settings(BaseSettings):
    """
    MyAsset Backend 전체 설정
    - pydantic-settings를 사용하여 환경변수 및 .env 파일 로드
    - 필수 환경변수 검증
    """
    # 기본 정보
    app_name: str = "MyAsset Portfolio Backend"
    debug: bool = False
    
    # DB 설정
    database_url: str = Field(default_factory=_get_default_db_url, validation_alias="DATABASE_URL")
    
    # 인증 (보안을 위해 SecretStr 사용을 고려할 수 있으나 편의상 str 유지)
    api_token: Optional[str] = Field(default=None, validation_alias="API_TOKEN")
    
    # 외부 API 통합 (PandaScore, Naver 등)
    open_api_key: Optional[str] = Field(default=None, validation_alias="OPEN_API_KEY")
    pandascore_api_key: Optional[str] = Field(default=None, validation_alias="PANDASCORE_API_KEY")
    naver_client_id: Optional[str] = Field(default=None, validation_alias="NAVER_CLIENT_ID")
    naver_client_secret: Optional[str] = Field(default=None, validation_alias="NAVER_CLIENT_SECRET")
    kma_service_key: Optional[str] = Field(default=None, validation_alias="KMA_SERVICE_KEY")
    kma_service_key1: Optional[str] = Field(default=None, validation_alias="KMA_SERVICE_KEY1")
    fred_api_key: Optional[str] = Field(default=None, validation_alias="FRED_API_KEY")
    bok_ecos_api_key: Optional[str] = Field(default=None, validation_alias="BOK_ECOS_API_KEY")
    
    # 알림 (Telegram)
    telegram_bot_token: Optional[str] = Field(default=None, validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, validation_alias="TELEGRAM_CHAT_ID")
    
    # LLM 및 AI 서비스 (llama-server 등)
    google_token: Optional[str] = Field(default=None, validation_alias="GOOGLE_TOKEN")
    llm_base_url: Optional[str] = Field(default=None, validation_alias="LLM_BASE_URL")
    llm_api_key: Optional[str] = Field(default=None, validation_alias="LLM_API_KEY")
    llm_timeout: float = Field(default=120.0, validation_alias="LLM_TIMEOUT")
    
    # AI 리포트 (유료 모델/OpenAI 등)
    ai_report_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="AI_REPORT_BASE_URL")
    ai_report_api_key: Optional[str] = Field(default=None, validation_alias="AI_REPORT_API_KEY")
    ai_report_model: str = Field(default="gpt-5.2", validation_alias="AI_REPORT_MODEL")
    ai_report_model_yearly: str = Field(default="gpt-5.2-pro", validation_alias="AI_REPORT_MODEL_YEARLY")
    ai_report_fallback_model: str = Field(validation_alias="AI_REPORT_FALLBACK_MODEL")
    ai_report_temperature: float = Field(default=0.3, validation_alias="AI_REPORT_TEMPERATURE")
    ai_report_max_tokens: int = Field(default=8000, validation_alias="AI_REPORT_MAX_TOKENS")
    ai_report_timeout_sec: float = Field(default=900.0, validation_alias="AI_REPORT_TIMEOUT_SEC")
    morning_openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias="MORNING_OPENROUTER_BASE_URL",
    )
    morning_openrouter_model: str = Field(
        default="google/gemini-3-flash-preview",
        validation_alias="MORNING_OPENROUTER_MODEL",
    )
    morning_allow_paid_fallback: bool = Field(
        default=False,
        validation_alias="MORNING_ALLOW_PAID_FALLBACK",
    )

    # 원격 모델 관리
    llm_remote_url: str = Field(default="http://localhost:8080", validation_alias="LLM_REMOTE_URL")
    llm_remote_default_model: str = Field(default="EXAONE-4.0-1.2B-Instruct-Q8_0.gguf", validation_alias="LLM_REMOTE_DEFAULT_MODEL")
    llm_remote_model_dir: str = Field(default="/data", validation_alias="LLM_REMOTE_MODEL_DIR")
    llm_remote_model_path_file: Optional[str] = Field(default=None, validation_alias="LLM_REMOTE_MODEL_PATH_FILE")

    # KIS (한국투자증권) 설정
    kis_config_dir: Optional[str] = Field(default=None, validation_alias="KIS_CONFIG_DIR")
    kis_enabled: str = Field(default="auto", validation_alias="KIS_ENABLED")
    kis_my_app: Optional[str] = Field(default=None, validation_alias="KIS_MY_APP")
    kis_my_sec: Optional[str] = Field(default=None, validation_alias="KIS_MY_SEC")
    kis_my_acct_stock: Optional[str] = Field(default=None, validation_alias="KIS_MY_ACCT_STOCK")
    kis_my_prod: Optional[str] = Field(default=None, validation_alias="KIS_MY_PROD")
    kis_my_app1: Optional[str] = Field(default=None, validation_alias="KIS_MY_APP1")
    kis_my_sec1: Optional[str] = Field(default=None, validation_alias="KIS_MY_SEC1")
    kis_my_acct_stock1: Optional[str] = Field(default=None, validation_alias="KIS_MY_ACCT_STOCK1")
    kis_my_prod1: Optional[str] = Field(default=None, validation_alias="KIS_MY_PROD1")
    kis_my_htsid: Optional[str] = Field(default=None, validation_alias="KIS_MY_HTSID")
    kis_prod: Optional[str] = Field(default=None, validation_alias="KIS_PROD")
    kis_ops: Optional[str] = Field(default=None, validation_alias="KIS_OPS")
    kis_vps: Optional[str] = Field(default=None, validation_alias="KIS_VPS")
    kis_vops: Optional[str] = Field(default=None, validation_alias="KIS_VOPS")
    kis_my_agent: Optional[str] = Field(default=None, validation_alias="KIS_MY_AGENT")
    kis_my_token: Optional[str] = Field(default=None, validation_alias="KIS_MY_TOKEN")
    kis_token_key: Optional[str] = Field(default=None, validation_alias="KIS_TOKEN_KEY")

    # 보안 (CORS)
    allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,https://personal-portfolio-blue-one-38.vercel.app,http://100.65.50.67,http://100.110.172.108",
        validation_alias="ALLOWED_ORIGINS"
    )

    # JWT 인증 설정
    jwt_secret_key: str = Field(..., validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(default=1440, validation_alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES")

    # 네이버 OAuth 설정
    naver_redirect_uri: str = Field(
        default="http://localhost:3000/auth/callback",
        validation_alias="NAVER_REDIRECT_URI"
    )
    # 접근 제어: 허용된 네이버 아이디 목록 (쉼표로 구분)
    naver_allowed_ids: str = Field(
        default="nav654",
        validation_alias="NAVER_ALLOWED_IDS"
    )


    model_config = SettingsConfigDict(
        env_file=get_project_env_file_strings(),
        env_file_encoding="utf-8",
        extra="ignore"
    )

import sys

# ... (생략) ...

try:
    # 싱글톤 설정 인스턴 생성
    # 인스턴스화 시점에 환경변수 검증이 수행됨
    settings = Settings()
except Exception as e:
    print(f"\n[CRITICAL ERROR] 설정 로드 실패 (환경변수 확인 필요): {e}\n", file=sys.stderr)
    sys.exit(1)
