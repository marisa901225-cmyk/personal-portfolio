import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _resolve_backend_dir_abs() -> str:
    # backend/services/llm/config.py -> backend/
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


BACKEND_DIR_ABS = _resolve_backend_dir_abs()
DATA_DIR_ABS = os.path.join(BACKEND_DIR_ABS, "data")
DATA_DIR_REL = os.path.join("backend", "data")

# 경로 상수 (원격 모드 전용)
REMOTE_MODEL_PATH_FILE = os.getenv(
    "LLM_REMOTE_MODEL_PATH_FILE",
    os.path.join(DATA_DIR_ABS, "llm_model_path.txt"),
)
REMOTE_MODEL_DIR = os.getenv("LLM_REMOTE_MODEL_DIR", "/data")
DEFAULT_MODEL_FILENAME = os.getenv("LLM_REMOTE_DEFAULT_MODEL", "EXAONE-4.0-1.2B-BF16.gguf")


class Settings:
    """
    LLM 설정 및 환경 변수 관리 (원격/유료 백엔드 공용)
    """

    def __init__(self):
        self.llm_base_url = (os.getenv("LLM_BASE_URL") or "").strip() or None
        self.llm_api_key = (os.getenv("LLM_API_KEY") or "").strip() or None
        self.llm_timeout = float(os.getenv("LLM_TIMEOUT", "120"))

        # 유료 모델용
        self.ai_report_base_url = os.getenv("AI_REPORT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.ai_report_api_key = (os.getenv("AI_REPORT_API_KEY") or "").strip() or None
        self.ai_report_model = (os.getenv("AI_REPORT_MODEL", "gpt-5.2") or "gpt-5.2").strip()

        self.backend_dir_abs = BACKEND_DIR_ABS
        self.data_dir_abs = DATA_DIR_ABS
        self.data_dir_rel = DATA_DIR_REL
        self.remote_model_path_file = REMOTE_MODEL_PATH_FILE

        self.current_model_path = self._initialize_model_path()

    def is_remote_configured(self) -> bool:
        return bool(self.llm_base_url)

    def is_paid_configured(self) -> bool:
        return bool(self.ai_report_api_key)

    def _initialize_model_path(self) -> str:
        """현재 활성화된 모델의 로컬 표시 경로를 결정한다."""
        return self.load_remote_model_path() or os.path.join(self.data_dir_rel, DEFAULT_MODEL_FILENAME)

    def load_remote_model_path(self) -> Optional[str]:
        remote_path = self.read_remote_model_path_raw()
        if not remote_path:
            return None
        return self.to_local_model_path(remote_path)

    def read_remote_model_path_raw(self) -> Optional[str]:
        """llm_model_path.txt에서 실제 원격 경로를 읽어온다."""
        if not os.path.exists(REMOTE_MODEL_PATH_FILE):
            return None
        try:
            with open(REMOTE_MODEL_PATH_FILE, "r") as f:
                raw = f.read().strip()
                if not raw: return None
                
                # 경로 정규화 (원격 llama-server 기준)
                if raw.startswith(("backend/data/", "/app/backend/data/")):
                    filename = os.path.basename(raw)
                    return f"{REMOTE_MODEL_DIR.rstrip('/')}/{filename}"
                if raw.startswith("/"):
                    return raw
                return f"{REMOTE_MODEL_DIR.rstrip('/')}/{raw}"
        except Exception as e:
            logger.error(f"Failed to read remote model path file: {e}")
        return None

    def write_remote_model_path(self, remote_path: str) -> bool:
        """원격 모델 경로를 파일에 저장하여 llama-server가 감지할 수 있게 한다."""
        try:
            os.makedirs(os.path.dirname(REMOTE_MODEL_PATH_FILE), exist_ok=True)
            with open(REMOTE_MODEL_PATH_FILE, "w") as f:
                f.write(remote_path)
            return True
        except Exception as e:
            logger.error(f"Failed to write remote model path file: {e}")
        return False

    @staticmethod
    def to_remote_model_path(local_path: str) -> str:
        filename = os.path.basename(local_path)
        return f"{REMOTE_MODEL_DIR.rstrip('/')}/{filename}"

    @staticmethod
    def to_local_model_path(remote_path: str) -> str:
        filename = os.path.basename(remote_path)
        return os.path.join("backend", "data", filename)
