from __future__ import annotations

import os
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime

import yaml

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
if not os.path.exists(token_tmp):
    with open(token_tmp, "w+", encoding="utf-8"):
        pass


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


_ENV_MAP = {
    "my_app": "KIS_MY_APP",
    "my_sec": "KIS_MY_SEC",
    "my_acct_stock": "KIS_MY_ACCT_STOCK",
    "my_prod": "KIS_MY_PROD",
    "my_htsid": "KIS_MY_HTSID",
    "prod": "KIS_PROD",
    "ops": "KIS_OPS",
    "vps": "KIS_VPS",
    "vops": "KIS_VOPS",
    "my_agent": "KIS_MY_AGENT",
    "my_token": "KIS_MY_TOKEN",
}


def _load_cfg_from_env() -> dict:
    cfg = {}
    for key, env_key in _ENV_MAP.items():
        value = os.getenv(env_key)
        if value is not None and str(value).strip() != "":
            cfg[key] = value.strip()
    return cfg


def _load_cfg_from_file() -> dict:
    path = os.path.join(config_root, "kis_user.yaml")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="UTF-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader) or {}


def _load_cfg() -> dict:
    cfg = _load_cfg_from_file()
    env_cfg = _load_cfg_from_env()
    if env_cfg:
        cfg.update(env_cfg)
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
