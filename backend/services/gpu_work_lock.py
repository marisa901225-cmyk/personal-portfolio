from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux containers provide fcntl.
    fcntl = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

_DEFAULT_LOCK_PATH = Path(__file__).resolve().parents[1] / "data" / "gpu_heavy_work.lock"
_DEFAULT_TIMEOUT_SEC = 240.0
_LOG_WAIT_AFTER_SEC = 1.0


def _lock_path() -> Path:
    return Path(os.getenv("GPU_HEAVY_WORK_LOCK_FILE") or _DEFAULT_LOCK_PATH)


def _lock_timeout_sec() -> float:
    raw = os.getenv("GPU_HEAVY_WORK_LOCK_TIMEOUT_SEC")
    if not raw:
        return _DEFAULT_TIMEOUT_SEC
    try:
        return max(1.0, float(raw))
    except ValueError:
        return _DEFAULT_TIMEOUT_SEC


@contextmanager
def gpu_heavy_work_lock(label: str) -> Iterator[None]:
    """Serialize GPU-heavy LLM/ComfyUI work across backend processes."""
    if fcntl is None:
        yield
        return

    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout_sec = _lock_timeout_sec()
    started = time.monotonic()
    logged_wait = False

    with path.open("a+", encoding="utf-8") as lock_file:
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                elapsed = time.monotonic() - started
                if elapsed >= timeout_sec:
                    raise TimeoutError(f"Timed out waiting for GPU work lock ({label}, {elapsed:.1f}s)")
                if not logged_wait and elapsed >= _LOG_WAIT_AFTER_SEC:
                    logger.info("Waiting for GPU work lock: label=%s lock=%s", label, path)
                    logged_wait = True
                time.sleep(0.5)

        waited = time.monotonic() - started
        if waited >= _LOG_WAIT_AFTER_SEC:
            logger.info("Acquired GPU work lock after %.1fs: label=%s", waited, label)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
