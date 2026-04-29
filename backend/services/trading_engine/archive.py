from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.core.models_misc import TradingEngineArchive
from backend.core.time_utils import utcnow

from .config import TradeEngineConfig
from .state import load_state

logger = logging.getLogger(__name__)

_TRADE_DATE_PATTERN = re.compile(r"(\d{8})")


@dataclass(slots=True)
class TradingEngineArchiveResult:
    status: str
    archive_id: int | None
    archive_date: str
    archived_output_file_count: int
    removed_output_file_count: int
    covered_trade_dates: list[str]
    runlog_truncated: bool


def archive_trading_engine_weekly(
    db: Session,
    *,
    config: TradeEngineConfig,
    now: datetime | None = None,
) -> TradingEngineArchiveResult:
    now = now or datetime.now()
    archive_date = now.strftime("%Y%m%d")
    output_dir = Path(config.output_dir)
    state_path = Path(config.state_path)
    runlog_path = Path(config.runlog_path)

    output_files = _list_output_files(output_dir)
    inline_limit = max(1, int(getattr(config, "archive_inline_max_bytes", 1_000_000)))
    output_entries = [
        _serialize_file(path, logical_path=f"output/{path.name}", inline_max_bytes=inline_limit)
        for path in output_files
    ]
    state_entry = (
        _serialize_file(state_path, logical_path="state.json", inline_max_bytes=inline_limit)
        if state_path.exists()
        else None
    )
    runlog_entry = (
        _serialize_file(runlog_path, logical_path="runlog_current.log", inline_max_bytes=inline_limit)
        if _has_content(runlog_path)
        else None
    )
    covered_trade_dates = _covered_trade_dates(output_files)
    week_id = _load_week_id(state_path)

    if not output_entries and runlog_entry is None:
        return TradingEngineArchiveResult(
            status="NOOP",
            archive_id=None,
            archive_date=archive_date,
            archived_output_file_count=0,
            removed_output_file_count=0,
            covered_trade_dates=covered_trade_dates,
            runlog_truncated=False,
        )

    payload = {
        "output_files": output_entries,
        "state_snapshot": state_entry,
        "runlog_snapshot": runlog_entry,
    }
    manifest = {
        "output_files": [_without_content(entry) for entry in output_entries],
        "state_snapshot": _without_content(state_entry) if state_entry else None,
        "runlog_snapshot": _without_content(runlog_entry) if runlog_entry else None,
    }

    archive_row = TradingEngineArchive(
        archive_date=archive_date,
        archive_kind="weekly_cleanup",
        week_id=week_id,
        covered_trade_dates_json=json.dumps(covered_trade_dates, ensure_ascii=False),
        manifest_json=json.dumps(manifest, ensure_ascii=False),
        payload_json=json.dumps(payload, ensure_ascii=False),
        archived_output_file_count=len(output_entries),
        removed_output_file_count=0,
    )
    db.add(archive_row)
    db.commit()
    db.refresh(archive_row)

    removed_output_file_count = 0
    runlog_truncated = False
    cleanup_error: str | None = None
    try:
        for path in output_files:
            entry = next((item for item in output_entries if item.get("name") == path.name), None)
            if not entry or not entry.get("inline_archived", False):
                continue
            path.unlink(missing_ok=True)
            removed_output_file_count += 1

        if runlog_entry is not None and runlog_entry.get("inline_archived", False):
            runlog_path.parent.mkdir(parents=True, exist_ok=True)
            runlog_path.write_text("", encoding="utf-8")
            runlog_truncated = True
    except OSError as exc:
        cleanup_error = str(exc)
        logger.error("trading engine weekly archive cleanup failed: %s", exc, exc_info=True)

    archive_row.removed_output_file_count = removed_output_file_count
    archive_row.cleanup_completed_at = utcnow() if cleanup_error is None else None
    archive_row.cleanup_error = cleanup_error
    db.add(archive_row)
    db.commit()

    if cleanup_error is not None:
        raise OSError(cleanup_error)

    logger.info(
        "trading engine weekly archive stored archive_id=%s files=%s removed=%s dates=%s runlog_truncated=%s",
        archive_row.id,
        len(output_entries),
        removed_output_file_count,
        covered_trade_dates,
        runlog_truncated,
    )
    return TradingEngineArchiveResult(
        status="ARCHIVED",
        archive_id=archive_row.id,
        archive_date=archive_date,
        archived_output_file_count=len(output_entries),
        removed_output_file_count=removed_output_file_count,
        covered_trade_dates=covered_trade_dates,
        runlog_truncated=runlog_truncated,
    )


def _list_output_files(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted(path for path in output_dir.iterdir() if path.is_file())


def _serialize_file(path: Path, *, logical_path: str, inline_max_bytes: int) -> dict[str, Any]:
    raw = path.read_bytes()
    stat = path.stat()
    entry = {
        "name": path.name,
        "path": logical_path,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "inline_archived": len(raw) <= inline_max_bytes,
    }
    if len(raw) > inline_max_bytes:
        entry["encoding"] = "omitted"
        entry["omitted_reason"] = f"size_exceeds_inline_limit:{inline_max_bytes}"
        entry["retained_on_disk"] = True
        return entry

    encoding = "utf-8"
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        encoding = "base64"
        content = base64.b64encode(raw).decode("ascii")
    entry["encoding"] = encoding
    entry["content"] = content
    entry["retained_on_disk"] = False
    return entry


def _without_content(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key != "content"}


def _covered_trade_dates(output_files: list[Path]) -> list[str]:
    dates = {
        matched.group(1)
        for path in output_files
        for matched in [_TRADE_DATE_PATTERN.search(path.name)]
        if matched is not None
    }
    return sorted(dates)


def _load_week_id(state_path: Path) -> str | None:
    if not state_path.exists():
        return None
    try:
        return load_state(str(state_path)).week_id
    except Exception:
        logger.warning("failed to read trading engine state for archive week_id", exc_info=True)
        return None


def _has_content(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False
