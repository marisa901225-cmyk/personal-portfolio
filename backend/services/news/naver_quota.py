from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import fcntl


KST = ZoneInfo("Asia/Seoul")
_INPROCESS_LOCK = threading.Lock()


class NaverQuotaStateError(RuntimeError):
    """Raised when the shared quota state cannot be trusted."""


@dataclass(frozen=True)
class NaverQuotaReservation:
    allowed: bool
    day: str
    month: str
    daily_used: int
    daily_limit: int
    monthly_used: int
    monthly_limit: int


@dataclass(frozen=True)
class _QuotaState:
    day: str
    month: str
    daily_used: int
    monthly_used: int


@contextmanager
def _exclusive_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _INPROCESS_LOCK:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_state(state_path: Path, *, day: str, month: str) -> _QuotaState:
    if not state_path.exists():
        return _QuotaState(day=day, month=month, daily_used=0, monthly_used=0)

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NaverQuotaStateError(f"Cannot read NAVER API quota state: {state_path}") from exc

    if not isinstance(payload, dict):
        raise NaverQuotaStateError(f"Invalid NAVER API quota state: {state_path}")

    try:
        stored_day = str(payload["day"])
        stored_month = str(payload["month"])
        daily_used = int(payload["daily_used"])
        monthly_used = int(payload["monthly_used"])
    except (KeyError, TypeError, ValueError) as exc:
        raise NaverQuotaStateError(f"Invalid NAVER API quota fields: {state_path}") from exc

    if daily_used < 0 or monthly_used < 0:
        raise NaverQuotaStateError(f"Negative NAVER API quota count: {state_path}")

    if stored_month != month:
        return _QuotaState(day=day, month=month, daily_used=0, monthly_used=0)
    if stored_day != day:
        return _QuotaState(day=day, month=month, daily_used=0, monthly_used=monthly_used)
    return _QuotaState(
        day=day,
        month=month,
        daily_used=daily_used,
        monthly_used=monthly_used,
    )


def _write_state(state_path: Path, state: _QuotaState, *, updated_at: datetime) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_name(f"{state_path.name}.{os.getpid()}.tmp")
    payload = {
        "day": state.day,
        "month": state.month,
        "daily_used": state.daily_used,
        "monthly_used": state.monthly_used,
        "updated_at": updated_at.isoformat(),
    }
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(state_path)
    finally:
        temp_path.unlink(missing_ok=True)


def reserve_naver_api_call(
    *,
    state_path: Path,
    daily_limit: int,
    monthly_limit: int,
    now: datetime | None = None,
) -> NaverQuotaReservation:
    if daily_limit < 1 or monthly_limit < 1:
        raise ValueError("NAVER API quota limits must be positive")

    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    current = current.astimezone(KST)
    day = current.date().isoformat()
    month = current.strftime("%Y-%m")
    resolved_state_path = Path(state_path)
    lock_path = resolved_state_path.with_name(f"{resolved_state_path.name}.lock")

    with _exclusive_lock(lock_path):
        state = _read_state(resolved_state_path, day=day, month=month)
        allowed = state.daily_used < daily_limit and state.monthly_used < monthly_limit
        if allowed:
            state = _QuotaState(
                day=day,
                month=month,
                daily_used=state.daily_used + 1,
                monthly_used=state.monthly_used + 1,
            )
            _write_state(resolved_state_path, state, updated_at=current)

        return NaverQuotaReservation(
            allowed=allowed,
            day=day,
            month=month,
            daily_used=state.daily_used,
            daily_limit=daily_limit,
            monthly_used=state.monthly_used,
            monthly_limit=monthly_limit,
        )


__all__ = [
    "NaverQuotaReservation",
    "NaverQuotaStateError",
    "reserve_naver_api_call",
]
