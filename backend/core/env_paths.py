from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SECRETS_ENV_FILE = Path.home() / "ai-models" / "myasset.secrets.env"


def get_repo_env_file() -> Path:
    return BASE_DIR / ".env"


def get_secrets_env_file() -> Path:
    configured = os.getenv("MYASSET_SECRETS_ENV_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_SECRETS_ENV_FILE


def get_project_env_files() -> tuple[Path, Path]:
    return (get_repo_env_file(), get_secrets_env_file())


def get_project_env_file_strings() -> tuple[str, str]:
    return tuple(str(path) for path in get_project_env_files())
