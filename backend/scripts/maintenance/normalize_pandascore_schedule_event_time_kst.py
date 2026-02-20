import argparse
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
_UTC_TO_KST_OFFSET = timedelta(hours=9)

_KST_LINE_RE = re.compile(r"Start Time\s*\(KST\)\s*:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
_UTC_LINE_RE = re.compile(r"Start Time\s*\(UTC\)\s*:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
_UTC_Z_LINE_RE = re.compile(r"Start Time\s*:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")


def _default_db_path() -> Path:
    # Matches backend/core/db.py default path
    return Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db"


def _parse_sqlite_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    # Examples:
    # - 2026-01-17 08:00:00.000000
    # - 2026-01-17 08:00:00
    # Keep only up to seconds; we normalize on seconds granularity.
    base = s.split(".", 1)[0]
    try:
        return datetime.fromisoformat(base)
    except Exception:
        return None


def _parse_expected_kst(full_content: str | None) -> datetime | None:
    if not full_content:
        return None

    m = _KST_LINE_RE.search(full_content)
    if m:
        try:
            return datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
        except Exception:
            return None

    m = _UTC_LINE_RE.search(full_content)
    if m:
        try:
            dt_utc_naive = datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
            return (dt_utc_naive + _UTC_TO_KST_OFFSET)
        except Exception:
            return None

    m = _UTC_Z_LINE_RE.search(full_content)
    if m:
        try:
            dt_utc = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(KST).replace(tzinfo=None)
        except Exception:
            return None

    return None


@dataclass(frozen=True)
class _Change:
    row_id: int
    before: str | None
    after: str


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize PandaScore schedule event_time to KST naive using full_content as source of truth."
    )
    parser.add_argument("--db", default=os.getenv("PORTFOLIO_DB_PATH") or str(_default_db_path()))
    parser.add_argument("--apply", action="store_true", help="Apply updates (default: dry-run)")
    parser.add_argument("--limit", type=int, default=0, help="Max rows to update (0 = no limit)")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 2

    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    cur.execute(
        """
        SELECT id, event_time, full_content
        FROM game_news
        WHERE source_name = 'PandaScore' AND source_type = 'schedule'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    print(f"Loaded {len(rows)} PandaScore schedule rows.")

    changes: list[_Change] = []
    skipped_no_parse = 0
    for row_id, event_time, full_content in rows:
        current = _parse_sqlite_dt(event_time)
        expected = _parse_expected_kst(full_content)
        if not expected:
            skipped_no_parse += 1
            continue
        if not current:
            changes.append(_Change(row_id=row_id, before=event_time, after=expected.strftime("%Y-%m-%d %H:%M:%S")))
            continue
        if current != expected:
            changes.append(_Change(row_id=row_id, before=event_time, after=expected.strftime("%Y-%m-%d %H:%M:%S")))

    print(f"Parsed expected KST for {len(rows) - skipped_no_parse} rows; {skipped_no_parse} rows skipped (no time line).")
    print(f"Changes needed: {len(changes)}")

    if not args.apply:
        for c in changes[:10]:
            print(f"- id={c.row_id} event_time: {c.before} -> {c.after}")
        if len(changes) > 10:
            print(f"... ({len(changes) - 10} more)")
        print("Dry-run only. Re-run with --apply to write changes.")
        return 0

    to_apply = changes[: args.limit] if args.limit and args.limit > 0 else changes
    for c in to_apply:
        cur.execute("UPDATE game_news SET event_time = ? WHERE id = ?", (c.after, c.row_id))
    con.commit()
    con.close()

    print(f"Applied {len(to_apply)} updates.")
    if args.limit and args.limit > 0 and len(changes) > len(to_apply):
        print(f"Remaining (not applied due to --limit): {len(changes) - len(to_apply)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
