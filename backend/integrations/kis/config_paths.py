from __future__ import annotations

import os
from pathlib import Path

from backend.core.config import settings


# 프로젝트 루트를 기준으로 한 기본 설정 경로
DEFAULT_KIS_CONFIG_DIR = Path(__file__).resolve().parents[2] / "storage" / "kis_config"


def get_kis_config_dir_if_configured() -> Path | None:
    configured = os.getenv("KIS_CONFIG_DIR") or settings.kis_config_dir
    if configured and str(configured).strip():
        return Path(str(configured)).expanduser()
    return None


def get_kis_config_dir() -> Path:
    """
    KIS 설정 디렉토리 경로를 반환한다.
    기본적으로 프로젝트 내부의 storage/kis_config를 우선하며, 
    환경변수 KIS_CONFIG_DIR가 설정된 경우 해당 경로를 따른다.
    """
    return get_kis_config_dir_if_configured() or DEFAULT_KIS_CONFIG_DIR


def ensure_kis_config_dir() -> Path:
    path = get_kis_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_kis_user_config_path() -> Path:
    return get_kis_config_dir() / "kis_user.yaml"


def get_kis_token_lock_path() -> Path:
    return get_kis_config_dir() / "KIS.token.lock"


def get_kis_token_tmp_path(date_yyyymmdd: str) -> Path:
    return get_kis_config_dir() / f"KIS{date_yyyymmdd}"
