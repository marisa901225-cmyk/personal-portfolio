from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.core.models_misc import SyncSchedulerLogArchive
from backend.core.time_utils import utcnow

logger = logging.getLogger(__name__)

_LEGACY_LOG_RE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s*-\s*"
    r"(?P<logger>[^-]+?)\s*-\s*(?P<level>[A-Z]+)\s*-\s*(?P<message>.*)$"
)
_HIGH_SIGNAL_INFO_PATTERNS = (
    "Current System Time",
    "Starting Price Sync Scheduler",
    "Market prices synced successfully.",
    "Portfolio snapshot captured successfully.",
    "DB Backup completed successfully",
    "Rate change alert sent.",
    "No rate changes detected.",
    "KODEX KOSPI100 daily warning sent=",
    "KODEX KOSPI100 weekly confirmation sent=",
    "LLM classified as SPAM:",
    "Spam filtered by DB rule",
    "Election/Political spam filtered:",
    "Review/Event spam filtered:",
)
_NOISY_MESSAGE_PATTERNS = (
    "Adding job tentatively",
    "Added job ",
    "Running job ",
    'Job "',
    "--- Starting Alarm Processing Job ---",
    "--- Alarm Processing Job Finished ---",
    "Alarm processing completed successfully.",
    "Generating random wisdom",
    "Recent categories saved",
    "Last random topic state updated",
    "HTTP Request: POST https://api.telegram.org/",
    "LLM Chat Messages:",
    "LLM Response:",
)


@dataclass(slots=True)
class SyncSchedulerLogArchiveResult:
    status: str
    archive_id: int | None
    archive_date: str
    total_line_count: int
    kept_line_count: int
    retained_tail_line_count: int
    dropped_line_count: int
    truncated: bool


def archive_sync_scheduler_log(
    db: Session,
    *,
    log_path: str,
    source_name: str = "sync_prices_scheduler",
    now: datetime | None = None,
    retain_tail_lines: int = 400,
) -> SyncSchedulerLogArchiveResult:
    now = now or datetime.now()
    archive_date = now.strftime("%Y%m%d")
    path = Path(log_path)

    if not path.exists() or path.stat().st_size == 0:
        return SyncSchedulerLogArchiveResult(
            status="NOOP",
            archive_id=None,
            archive_date=archive_date,
            total_line_count=0,
            kept_line_count=0,
            retained_tail_line_count=0,
            dropped_line_count=0,
            truncated=False,
        )

    raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total_line_count = len(raw_lines)
    kept_entries: list[dict[str, Any]] = []
    kept_reason_counts: dict[str, int] = {}

    for line_no, raw_line in enumerate(raw_lines, start=1):
        entry = _parse_log_line(raw_line, line_no=line_no)
        if entry is None:
            continue
        reason = _keep_reason(entry)
        if reason is None:
            continue
        entry["keep_reason"] = reason
        kept_entries.append(entry)
        kept_reason_counts[reason] = kept_reason_counts.get(reason, 0) + 1

    retained_lines = raw_lines[-max(0, retain_tail_lines):] if retain_tail_lines > 0 else []
    manifest = {
        "source_name": source_name,
        "log_path": str(path),
        "total_line_count": total_line_count,
        "kept_line_count": len(kept_entries),
        "dropped_line_count": max(0, total_line_count - len(kept_entries)),
        "retained_tail_line_count": len(retained_lines),
        "keep_reason_counts": kept_reason_counts,
    }
    payload = {
        "entries": kept_entries,
    }

    archive_row = SyncSchedulerLogArchive(
        archive_date=archive_date,
        source_name=source_name,
        log_path=str(path),
        total_line_count=total_line_count,
        kept_line_count=len(kept_entries),
        retained_tail_line_count=len(retained_lines),
        dropped_line_count=max(0, total_line_count - len(kept_entries)),
        manifest_json=json.dumps(manifest, ensure_ascii=False),
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(archive_row)
    db.commit()
    db.refresh(archive_row)

    cleanup_error: str | None = None
    truncated = False
    try:
        normalized_tail = "\n".join(retained_lines).rstrip()
        path.write_text((normalized_tail + "\n") if normalized_tail else "", encoding="utf-8")
        truncated = True
    except OSError as exc:
        cleanup_error = str(exc)
        logger.error("sync scheduler log cleanup failed: %s", exc, exc_info=True)

    archive_row.cleanup_completed_at = utcnow() if cleanup_error is None else None
    archive_row.cleanup_error = cleanup_error
    db.add(archive_row)
    db.commit()

    if cleanup_error is not None:
        raise OSError(cleanup_error)

    logger.info(
        "sync scheduler log archive stored archive_id=%s total=%s kept=%s retained_tail=%s",
        archive_row.id,
        total_line_count,
        len(kept_entries),
        len(retained_lines),
    )
    return SyncSchedulerLogArchiveResult(
        status="ARCHIVED",
        archive_id=archive_row.id,
        archive_date=archive_date,
        total_line_count=total_line_count,
        kept_line_count=len(kept_entries),
        retained_tail_line_count=len(retained_lines),
        dropped_line_count=max(0, total_line_count - len(kept_entries)),
        truncated=truncated,
    )


def _parse_log_line(raw_line: str, *, line_no: int) -> dict[str, Any] | None:
    stripped = (raw_line or "").strip()
    if not stripped:
        return None

    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return {
                "line_no": line_no,
                "raw": raw_line,
                "timestamp": payload.get("timestamp"),
                "level": str(payload.get("level") or "").upper(),
                "logger": str(payload.get("logger") or ""),
                "message": str(payload.get("message") or ""),
                "format": "json",
            }

    matched = _LEGACY_LOG_RE.match(stripped)
    if matched:
        return {
            "line_no": line_no,
            "raw": raw_line,
            "timestamp": matched.group("timestamp"),
            "level": matched.group("level").upper(),
            "logger": matched.group("logger").strip(),
            "message": matched.group("message"),
            "format": "legacy",
        }

    return None


def _keep_reason(entry: dict[str, Any]) -> str | None:
    level = str(entry.get("level") or "").upper()
    logger_name = str(entry.get("logger") or "")
    message = str(entry.get("message") or "")

    if any(pattern in message for pattern in _NOISY_MESSAGE_PATTERNS):
        return None

    if level in {"WARNING", "ERROR", "CRITICAL"}:
        return "warning_or_error"

    if level != "INFO":
        return None

    if logger_name == "backend.services.alarm.filters" and any(
        token in message
        for token in (
            "LLM classified as SPAM:",
            "Spam filtered by DB rule",
            "Election/Political spam filtered:",
            "Review/Event spam filtered:",
        )
    ):
        return "spam_filter_event"

    if logger_name == "sync_prices_scheduler" and any(pattern in message for pattern in _HIGH_SIGNAL_INFO_PATTERNS):
        return "scheduler_info"

    return None
