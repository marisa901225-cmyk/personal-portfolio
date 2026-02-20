from __future__ import annotations

import logging
import os
import sys
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime

import yaml

from backend.core.config import settings
from backend.integrations.kis.config_paths import (
    ensure_kis_config_dir,
    get_kis_config_dir,
    get_kis_config_dir_if_configured,
    get_kis_token_lock_path,
    get_kis_token_tmp_path,
    get_kis_user_config_path,
)

try:
    import fcntl
except Exception:
    fcntl = None

clearConsole = lambda: os.system("cls" if os.name in ("nt", "dos") else "clear")

key_bytes = 32
_inprocess_token_lock = threading.Lock()

# Globals will be initialized lazily
config_root = ""
token_tmp = ""
token_lock = ""
_cfg: dict | None = None


def _resolve_config_root() -> str:
    """
    Resolve KIS config directory.
    Priority 1: Environment variable or settings
    Priority 2: DEFAULT_KIS_CONFIG_DIR from config_paths
    """
    return str(get_kis_config_dir())


def reload_paths() -> None:
    global config_root, token_tmp, token_lock
    # This function is now safer as it doesn't create directories
    config_root = _resolve_config_root()
    token_tmp = str(get_kis_token_tmp_path(datetime.today().strftime("%Y%m%d")))
    token_lock = str(get_kis_token_lock_path())


def _ensure_config_root() -> None:
    """Create config directory only when needed (lazy)."""
    ensure_kis_config_dir()
    reload_paths()


@contextmanager
def _token_file_lock():
    with _inprocess_token_lock:
        if fcntl is None:
            yield
            return
        
        _ensure_config_root()
        with open(token_lock, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_cfg_from_file() -> dict:
    # Always reload paths before using them to ensure we use the latest env vars
    reload_paths()
    path = get_kis_user_config_path()
    if not path.exists():
        return {}
    with open(path, encoding="UTF-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader) or {}


def _load_cfg() -> dict:
    # 1. Start with file config (if exists)
    cfg = _load_cfg_from_file()
    
    # 2. Overwrite with Settings (centered environment variables)
    settings_cfg = {
        "my_app": settings.kis_my_app,
        "my_sec": settings.kis_my_sec,
        "my_acct_stock": settings.kis_my_acct_stock,
        "my_prod": settings.kis_my_prod,
        "my_htsid": settings.kis_my_htsid,
        "prod": settings.kis_prod,
        "ops": settings.kis_ops,
        "vps": settings.kis_vps,
        "vops": settings.kis_vops,
        "my_agent": settings.kis_my_agent,
        "my_token": settings.kis_my_token,
    }
    
    # Filter out None and empty strings
    env_cfg = {k: v for k, v in settings_cfg.items() if v is not None and str(v).strip() != ""}
    
    if env_cfg:
        cfg.update(env_cfg)

    # Ensure mandatory keys have at least default values to avoid KeyErrors
    defaults = {
        "my_prod": "01",
        "prod": "https://openapi.koreainvestment.com:9443",
        "vps": "https://openapivts.koreainvestment.com:29443",
        "ops": "ws://ops.koreainvestment.com:21000",
        "vops": "ws://ops.koreainvestment.com:31000",
    }
    for k, v in defaults.items():
        if not cfg.get(k):
            cfg[k] = v
            
    return cfg


def _is_config_ready() -> bool:
    """Check if mandatory config keys are present."""
    cfg = get_cfg()
    mandatory = ["my_app", "my_sec", "my_acct_stock"]
    return all(cfg.get(k) for k in mandatory)


def get_cfg() -> dict:
    global _cfg
    if _cfg is None:
        _cfg = _load_cfg()
        if _cfg and "my_agent" in _cfg:
            _base_headers["User-Agent"] = _cfg["my_agent"]
    return _cfg or {}


def reload_config() -> None:
    global _cfg
    _cfg = None  # Force reload on next get_cfg()
    get_cfg()


_TRENV: Any | None = None
_last_auth_time = datetime.now()
_autoReAuth = False
_DEBUG = False
_isPaper = False
_smartSleep = 0.1

# REST rate limit: 20 requests per second (per appkey)
_REST_RATE_LIMIT = 20
_REST_RATE_WINDOW = 1.0
_rest_rate_lock = threading.Lock()
_rest_rate_timestamps = deque()

_base_headers = {
    "Content-Type": "application/json",
    "Accept": "text/plain",
    "charset": "UTF-8",
    "User-Agent": "MyAsset", # Will be updated by get_cfg()
}

_base_headers_ws = {
    "content-type": "utf-8",
}


def __getattr__(name: str):
    if name == "_cfg":
        return get_cfg()
    raise AttributeError(f"module {__name__} has no attribute {name}")
