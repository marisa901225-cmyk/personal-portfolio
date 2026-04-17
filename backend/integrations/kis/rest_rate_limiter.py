from __future__ import annotations

import json
import logging
import os
import hashlib
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

try:
    import fcntl
except Exception:  # pragma: no cover - non-Unix fallback
    fcntl = None

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT_PER_SEC = 20
_DEFAULT_WINDOW_SEC = 1.0
_LOCK_FILE_NAME = "KIS.rest_rate.lock"
_STATE_FILE_NAME = "KIS.rest_rate.json"
_WRITE_TMP_SUFFIX = ".tmp"
_INPROCESS_LOCK = threading.Lock()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default=%s", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default=%s", name, raw, default)
        return default


def get_rest_rate_limit_per_sec() -> int:
    return max(1, _env_int("KIS_REST_RATE_LIMIT_PER_SEC", _DEFAULT_LIMIT_PER_SEC))


def get_rest_rate_window_sec() -> float:
    return max(0.001, _env_float("KIS_REST_RATE_WINDOW_SEC", _DEFAULT_WINDOW_SEC))


def _lock_path(config_dir: Path) -> Path:
    return config_dir / _LOCK_FILE_NAME


def _state_path(config_dir: Path) -> Path:
    return config_dir / _STATE_FILE_NAME


def _gap_state_path(config_dir: Path, scope: str) -> Path:
    digest = hashlib.sha1(scope.encode("utf-8")).hexdigest()[:12]
    return config_dir / f"KIS.rest_gap.{digest}.json"


@contextmanager
def _file_lock(lock_path: Path):
    if fcntl is None:
        yield
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_timestamps(state_path: Path) -> list[float]:
    if not state_path.exists():
        return []

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, dict):
        return []

    raw_timestamps = payload.get("timestamps", [])
    if not isinstance(raw_timestamps, list):
        return []

    timestamps: list[float] = []
    for item in raw_timestamps:
        try:
            timestamps.append(float(item))
        except (TypeError, ValueError):
            continue
    return timestamps


def _write_timestamps(state_path: Path, timestamps: list[float]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(state_path.name + _WRITE_TMP_SUFFIX)
    payload = {"timestamps": timestamps}
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(state_path)


def _read_last_timestamp(state_path: Path) -> float | None:
    if not state_path.exists():
        return None

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return None

    value = payload.get("last_timestamp")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_last_timestamp(state_path: Path, timestamp: float) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = state_path.with_name(state_path.name + _WRITE_TMP_SUFFIX)
    payload = {"last_timestamp": float(timestamp)}
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(state_path)


def throttle_rest_requests(
    *,
    limit_per_sec: int | None = None,
    window_sec: float | None = None,
    config_dir: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    resolved_limit = max(1, int(limit_per_sec if limit_per_sec is not None else get_rest_rate_limit_per_sec()))
    resolved_window = max(
        0.001,
        float(window_sec if window_sec is not None else get_rest_rate_window_sec()),
    )
    if config_dir is not None:
        resolved_config_dir = Path(config_dir)
    else:
        from backend.integrations.kis.config_paths import ensure_kis_config_dir

        resolved_config_dir = ensure_kis_config_dir()
    resolved_state_path = _state_path(resolved_config_dir)
    resolved_lock_path = _lock_path(resolved_config_dir)

    while True:
        with _INPROCESS_LOCK:
            with _file_lock(resolved_lock_path):
                now = float(clock())
                timestamps = [
                    ts for ts in _read_timestamps(resolved_state_path)
                    if now - ts < resolved_window
                ]
                if len(timestamps) < resolved_limit:
                    timestamps.append(now)
                    _write_timestamps(resolved_state_path, timestamps)
                    return

                sleep_for = resolved_window - (now - timestamps[0])

        sleeper(max(0.001, sleep_for))


def throttle_rest_min_gap(
    *,
    scope: str,
    min_gap_sec: float,
    config_dir: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    resolved_gap = max(0.0, float(min_gap_sec))
    if resolved_gap <= 0:
        return

    if config_dir is not None:
        resolved_config_dir = Path(config_dir)
    else:
        from backend.integrations.kis.config_paths import ensure_kis_config_dir

        resolved_config_dir = ensure_kis_config_dir()
    resolved_gap_state_path = _gap_state_path(resolved_config_dir, scope)
    resolved_lock_path = _lock_path(resolved_config_dir)

    while True:
        with _INPROCESS_LOCK:
            with _file_lock(resolved_lock_path):
                now = float(clock())
                last_timestamp = _read_last_timestamp(resolved_gap_state_path)
                if last_timestamp is None or now - last_timestamp >= resolved_gap:
                    _write_last_timestamp(resolved_gap_state_path, now)
                    return

                sleep_for = resolved_gap - (now - last_timestamp)

        sleeper(max(0.001, sleep_for))


__all__ = [
    "get_rest_rate_limit_per_sec",
    "get_rest_rate_window_sec",
    "throttle_rest_min_gap",
    "throttle_rest_requests",
]
