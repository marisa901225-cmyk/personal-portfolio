from __future__ import annotations

import os
import threading
import time
from typing import Callable

from fastapi import Header, HTTPException, Request, Response

DEFAULT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
DEFAULT_LIMIT = int(os.getenv("RATE_LIMIT_DEFAULT", "30"))
CLEANUP_INTERVAL_SEC = int(os.getenv("RATE_LIMIT_CLEANUP_SEC", "300"))
ALLOWLIST_RAW = os.getenv("RATE_LIMIT_ALLOWLIST", "")

_buckets: dict[str, tuple[int, float, int]] = {}
_lock = threading.Lock()
_last_cleanup = 0.0


def _parse_allowlist() -> set[str]:
    return {item.strip() for item in ALLOWLIST_RAW.split(",") if item.strip()}


def _is_allowlisted(request: Request, x_api_token: str | None) -> bool:
    allowlist = _parse_allowlist()
    if not allowlist:
        return False
    client = request.client.host if request.client else ""
    return (
        client in allowlist
        or (x_api_token is not None and x_api_token in allowlist)
        or f"ip:{client}" in allowlist
        or (x_api_token is not None and f"token:{x_api_token}" in allowlist)
    )


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
        response: Response,
        x_api_token: str | None = Header(default=None),
    ) -> None:
        if _is_allowlisted(request, x_api_token):
            return

        key = _get_key(request, x_api_token)
        bucket_key = f"{key_prefix}:{key}"
        now = time.monotonic()

        with _lock:
            count, window_start, bucket_window = _buckets.get(bucket_key, (0, now, effective_window))
            if bucket_window != effective_window:
                count = 0
                window_start = now
                bucket_window = effective_window

            elapsed = now - window_start
            if elapsed >= bucket_window:
                count = 0
                window_start = now
                elapsed = 0
            count += 1
            _buckets[bucket_key] = (count, window_start, bucket_window)

            global _last_cleanup
            if now - _last_cleanup >= CLEANUP_INTERVAL_SEC:
                expired_keys = [
                    k for k, (_, start, win) in _buckets.items()
                    if now - start >= win * 2
                ]
                for k in expired_keys:
                    _buckets.pop(k, None)
                _last_cleanup = now

        remaining = max(0, effective_limit - count)
        reset_in = max(0, int(bucket_window - elapsed))
        response.headers["X-RateLimit-Limit"] = str(effective_limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)

        if count > effective_limit:
            retry_after = max(0, int(bucket_window - elapsed))
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(effective_limit),
                    "X-RateLimit-Remaining": str(remaining),
                    "X-RateLimit-Reset": str(reset_in),
                },
            )

    return _dependency
