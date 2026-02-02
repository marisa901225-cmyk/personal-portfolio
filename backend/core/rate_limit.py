from __future__ import annotations

import os
import threading
import time
from typing import Callable

from fastapi import Header, HTTPException, Request

DEFAULT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
DEFAULT_LIMIT = int(os.getenv("RATE_LIMIT_DEFAULT", "30"))

_buckets: dict[str, tuple[int, float]] = {}
_lock = threading.Lock()


def _get_key(request: Request, x_api_token: str | None) -> str:
    if x_api_token:
        return f"token:{x_api_token}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


def rate_limit(
    limit: int | None = None,
    window_sec: int | None = None,
    key_prefix: str = "rl",
) -> Callable[[Request, str | None], None]:
    effective_limit = limit or DEFAULT_LIMIT
    effective_window = window_sec or DEFAULT_WINDOW_SEC

    def _dependency(
        request: Request,
        x_api_token: str | None = Header(default=None),
    ) -> None:
        key = _get_key(request, x_api_token)
        bucket_key = f"{key_prefix}:{key}"
        now = time.monotonic()

        with _lock:
            count, window_start = _buckets.get(bucket_key, (0, now))
            elapsed = now - window_start
            if elapsed >= effective_window:
                count = 0
                window_start = now
                elapsed = 0
            count += 1
            _buckets[bucket_key] = (count, window_start)

        if count > effective_limit:
            retry_after = max(0, int(effective_window - elapsed))
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
