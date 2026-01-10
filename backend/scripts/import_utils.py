from __future__ import annotations

import re
from datetime import date, datetime, time


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", name).upper()


def parse_date(value: str, formats: tuple[str, ...] | None = None) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    if formats is None:
        formats = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y%m%d")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value: str, formats: tuple[str, ...] | None = None) -> time | None:
    value = (value or "").strip()
    if not value:
        return None
    if formats is None:
        formats = ("%H:%M:%S", "%H:%M")
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def parse_number(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None
