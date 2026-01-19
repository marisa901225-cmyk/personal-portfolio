from __future__ import annotations

import os
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime

import yaml

from backend.core.config import settings

try:
    import fcntl
except Exception:
    fcntl = None

clearConsole = lambda: os.system("cls" if os.name in ("nt", "dos") else "clear")

key_bytes = 32
config_root = os.path.join(os.path.expanduser("~"), "KIS", "config")
token_tmp = os.path.join(config_root, f"KIS{datetime.today().strftime('%Y%m%d')}")
token_lock = os.path.join(config_root, "KIS.token.lock")

os.makedirs(config_root, exist_ok=True)


@contextmanager
def _token_file_lock():
    if fcntl is None:
        yield
        return
    with open(token_lock, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _load_cfg_from_file() -> dict:
    path = os.path.join(config_root, "kis_user.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="UTF-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader) or {}


def _load_cfg() -> dict:
    # 1. Start with file config (if exists)
    cfg = _load_cfg_from_file()
    
    # 2. Overwrite with Settings (centered environment variables)
    # Using getattr to be safe, but settings object should have these
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
        if k not in cfg:
            cfg[k] = v
            
    return cfg


def reload_config() -> None:
    global _cfg
    _cfg = _load_cfg()
    if "my_agent" in _cfg:
        _base_headers["User-Agent"] = _cfg["my_agent"]


_cfg = _load_cfg()

_TRENV = tuple()
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
    "User-Agent": _cfg.get("my_agent", "MyAsset"),
}

_base_headers_ws = {
    "content-type": "utf-8",
}
