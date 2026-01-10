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


with open(os.path.join(config_root, "kis_user.yaml"), encoding="UTF-8") as f:
    _cfg = yaml.load(f, Loader=yaml.FullLoader)

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
    "User-Agent": _cfg["my_agent"],
}

_base_headers_ws = {
    "content-type": "utf-8",
}
