import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
_KST_LINE_RE = re.compile(r"Start Time\s*\(KST\)\s*:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
_UTC_Z_LINE_RE = re.compile(r"Start Time\s*:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")
_TEAM_SPLIT_RE = re.compile(r"\s+(?:vs|v)\s+", re.IGNORECASE)


def ci_contains(col, needle: str):
    """Use icontains when available and fall back safely in tests."""
    if hasattr(col, "icontains"):
        return col.icontains(needle)  # type: ignore[attr-defined]
    if hasattr(col, "ilike"):
        return col.ilike(f"%{needle}%")  # type: ignore[attr-defined]
    return ("icontains_fallback", col, needle)


def parse_match_time_kst(full_content: str) -> datetime | None:
    if not full_content:
        return None

    match = _KST_LINE_RE.search(full_content)
    if match:
        try:
            return datetime.fromisoformat(f"{match.group(1)} {match.group(2)}")
        except Exception:
            return None

    match = _UTC_Z_LINE_RE.search(full_content)
    if match:
        try:
            dt_utc = datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(KST).replace(tzinfo=None)
        except Exception:
            return None

    return None


def format_match_time_kst(match, *, kst: ZoneInfo = KST) -> str:
    try:
        parsed = parse_match_time_kst(getattr(match, "full_content", "") or "")
        if parsed:
            return parsed.strftime("%H:%M")
    except Exception:
        pass

    dt = getattr(match, "event_time", None)
    if not dt:
        return "시간 미정"

    try:
        if getattr(dt, "tzinfo", None) is not None:
            return dt.astimezone(kst).strftime("%H:%M")
        dt_utc = dt.replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(kst).strftime("%H:%M")
    except Exception:
        return "시간 미정"


def extract_match_name(title: str) -> str:
    cleaned = (title or "").replace("[Esports Schedule] ", "").strip()
    if " - " in cleaned:
        return cleaned.split(" - ", 1)[1].strip()
    return cleaned


def extract_match_teams(title: str) -> tuple[str, str]:
    match_name = extract_match_name(title)
    if not match_name:
        return ("팀A", "팀B")

    if "⚔️" in match_name:
        parts = [part.strip() for part in match_name.split("⚔️", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])

    parts = [part.strip() for part in _TEAM_SPLIT_RE.split(match_name, 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        return (parts[0], parts[1])

    return ("팀A", "팀B")


def is_tbd_team_name(name: str) -> bool:
    normalized = (name or "").strip().casefold()
    return normalized in {"tbd", "tba"} or "tbd" in normalized or "tba" in normalized


def is_tbd_match_title(title: str) -> bool:
    team_a, team_b = extract_match_teams(title)
    return is_tbd_team_name(team_a) or is_tbd_team_name(team_b)
