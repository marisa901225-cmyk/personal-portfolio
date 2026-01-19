from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """
    Return the current UTC time as a *naive* datetime.

    We avoid `datetime.utcnow()` (deprecated in Python 3.12+) while preserving
    existing behavior in the codebase and DB layer (naive UTC timestamps).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
