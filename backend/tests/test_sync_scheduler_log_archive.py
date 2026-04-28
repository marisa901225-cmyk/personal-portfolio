from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.db import Base
from backend.core.models_misc import SyncSchedulerLogArchive
from backend.services.sync_scheduler_log_archive import archive_sync_scheduler_log


def test_archive_sync_scheduler_log_keeps_high_signal_events_and_trims_file(tmp_path) -> None:
    db_path = tmp_path / "archive.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)

    log_path = tmp_path / "sync_prices_scheduler.log"
    log_path.write_text(
        "\n".join(
            [
                '2026-04-21 15:45:00,029 - apscheduler.executors.default - INFO - Running job "Periodic Alarm Summary..."',
                "2026-04-21 15:45:00,035 - sync_prices_scheduler - INFO - --- Starting Alarm Processing Job ---",
                "2026-04-21 15:45:00,038 - sync_prices_scheduler - INFO - Alarm processing completed successfully.",
                '2026-04-21 15:50:00,462 - backend.services.alarm.filters - INFO - LLM classified as SPAM: [문피아] 테스트...',
                '{"timestamp": "2026-04-21 16:05:00,466", "level": "ERROR", "logger": "sync_prices_scheduler", "message": "Alarm processing job failed: boom"}',
                '{"timestamp": "2026-04-21 16:10:00,050", "level": "INFO", "logger": "backend.services.alarm.random_topic_service", "message": "Generating random wisdom (Attempt 1/2)..."}',
                '{"timestamp": "2026-04-21 16:12:00,000", "level": "INFO", "logger": "sync_prices_scheduler", "message": "KODEX KOSPI100 daily warning sent=False"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with SessionLocal() as db:
        result = archive_sync_scheduler_log(
            db,
            log_path=str(log_path),
            now=datetime(2026, 4, 21, 16, 30),
            retain_tail_lines=2,
        )
        row = db.query(SyncSchedulerLogArchive).one()
        manifest = json.loads(row.manifest_json)
        payload = json.loads(row.payload_json)

    assert result.status == "ARCHIVED"
    assert result.total_line_count == 7
    assert result.kept_line_count == 3
    assert result.retained_tail_line_count == 2
    assert result.dropped_line_count == 4
    assert manifest["keep_reason_counts"] == {
        "spam_filter_event": 1,
        "warning_or_error": 1,
        "scheduler_info": 1,
    }
    assert [entry["keep_reason"] for entry in payload["entries"]] == [
        "spam_filter_event",
        "warning_or_error",
        "scheduler_info",
    ]
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        '{"timestamp": "2026-04-21 16:10:00,050", "level": "INFO", "logger": "backend.services.alarm.random_topic_service", "message": "Generating random wisdom (Attempt 1/2)..."}',
        '{"timestamp": "2026-04-21 16:12:00,000", "level": "INFO", "logger": "sync_prices_scheduler", "message": "KODEX KOSPI100 daily warning sent=False"}',
    ]

    engine.dispose()


def test_archive_sync_scheduler_log_is_noop_for_missing_file(tmp_path) -> None:
    db_path = tmp_path / "archive.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        result = archive_sync_scheduler_log(
            db,
            log_path=str(tmp_path / "missing.log"),
            now=datetime(2026, 4, 21, 16, 30),
        )
        row_count = db.query(SyncSchedulerLogArchive).count()

    assert result.status == "NOOP"
    assert row_count == 0

    engine.dispose()
