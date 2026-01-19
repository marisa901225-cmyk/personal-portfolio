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

from ...core.config import settings

# 경로 상수 (원격 모드 전용)
REMOTE_MODEL_PATH_FILE = settings.llm_remote_model_path_file or os.path.join(DATA_DIR_ABS, "llm_model_path.txt")
REMOTE_MODEL_DIR = settings.llm_remote_model_dir
DEFAULT_MODEL_FILENAME = settings.llm_remote_default_model


class Settings:
    """
    LLM 설정 및 환경 변수 관리 (원격/유료 백엔드 공용)
    """

    def __init__(self):
        self.llm_base_url = settings.llm_base_url
        self.llm_api_key = settings.llm_api_key
        self.llm_timeout = settings.llm_timeout

        # 유료 모델용
        self.ai_report_base_url = settings.ai_report_base_url
        self.ai_report_api_key = settings.ai_report_api_key
        self.ai_report_model = settings.ai_report_model
        self.ai_report_fallback_model = settings.ai_report_fallback_model
        self.ai_report_timeout_sec = settings.ai_report_timeout_sec

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
        model_path_file = self.remote_model_path_file
        if not os.path.exists(model_path_file):
            return None
        try:
            with open(model_path_file, "r", encoding="utf-8") as f:
                raw = f.read().strip()
                if not raw:
                    return None
                
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
            model_path_file = self.remote_model_path_file
            os.makedirs(os.path.dirname(model_path_file), exist_ok=True)
            with open(model_path_file, "w", encoding="utf-8") as f:
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
