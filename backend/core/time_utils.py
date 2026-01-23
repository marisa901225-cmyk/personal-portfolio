from __future__ import annotations

from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def utcnow() -> datetime:
    """
    Return the current UTC time as a *naive* datetime.

    We avoid `datetime.utcnow()` (deprecated in Python 3.12+) while preserving
    existing behavior in the codebase and DB layer (naive UTC timestamps).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_kst() -> datetime:
    """Return the current time in KST timezone."""
    return datetime.now(KST)


def to_kst(dt: datetime) -> datetime:
    """Convert a datetime to KST timezone.
    
    Handles both naive (assumes UTC) and aware datetime objects.
    """
    if dt.tzinfo is None:
        # Naive datetime, assume UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)


def format_kst_time(dt: datetime, fmt: str = "%H:%M") -> str:
    """Format a datetime as KST time string."""
    return to_kst(dt).strftime(fmt)


def kst_time_to_minutes(dt: datetime) -> int:
    """Convert KST time to minutes since midnight (for time window checks)."""
    kst_dt = to_kst(dt)
    return kst_dt.hour * 60 + kst_dt.minute
