from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.db import Base
from backend.core.models_misc import TradingEngineArchive
from backend.services.trading_engine.archive import archive_trading_engine_weekly
from backend.services.trading_engine.bot import HybridTradingBot
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.journal import TradeJournal
from backend.services.trading_engine.state import new_state, save_state


class _SpyNotifier:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.files: list[tuple[str, str | None]] = []

    def enqueue_text(self, text: str) -> None:
        self.texts.append(text)

    def enqueue_file(self, path: str, caption: str | None = None) -> None:
        self.files.append((path, caption))

    def flush(self, timeout_sec: float = 2.0) -> None:
        del timeout_sec

    def close(self, timeout_sec: float = 2.0) -> None:
        del timeout_sec


def test_archive_trading_engine_weekly_moves_files_to_db_and_cleans_up(tmp_path) -> None:
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

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = output_dir / "trade_journal_20260414.jsonl"
    journal_path.write_text('{"event":"SCAN_DONE"}\n', encoding="utf-8")
    legacy_zip_path = output_dir / "trade_backup_20260414.zip"
    legacy_zip_path.write_bytes(b"\x50\x4b\x03\x04\xff")

    state_path = tmp_path / "state.json"
    state = new_state("20260418")
    save_state(str(state_path), state)

    runlog_path = tmp_path / "run.log"
    runlog_path.write_text("line one\nline two\n", encoding="utf-8")

    cfg = TradeEngineConfig(
        state_path=str(state_path),
        output_dir=str(output_dir),
        runlog_path=str(runlog_path),
    )

    with SessionLocal() as db:
        result = archive_trading_engine_weekly(
            db,
            config=cfg,
            now=datetime(2026, 4, 18, 6, 40),
        )
        row = db.query(TradingEngineArchive).one()
        payload_json = row.payload_json
        manifest_json = row.manifest_json
        cleanup_completed_at = row.cleanup_completed_at
        cleanup_error = row.cleanup_error

    payload = json.loads(payload_json)
    manifest = json.loads(manifest_json)
    archived_names = {item["name"] for item in payload["output_files"]}

    assert result.status == "ARCHIVED"
    assert result.archived_output_file_count == 2
    assert result.removed_output_file_count == 2
    assert result.runlog_truncated is True
    assert result.covered_trade_dates == ["20260414"]
    assert archived_names == {"trade_journal_20260414.jsonl", "trade_backup_20260414.zip"}
    assert payload["state_snapshot"]["name"] == "state.json"
    assert payload["runlog_snapshot"]["path"] == "runlog_current.log"
    assert any(item["encoding"] == "base64" for item in payload["output_files"])
    assert all("content" not in item for item in manifest["output_files"])
    assert cleanup_completed_at is not None
    assert cleanup_error is None
    assert not journal_path.exists()
    assert not legacy_zip_path.exists()
    assert state_path.exists()
    assert runlog_path.read_text(encoding="utf-8") == ""

    engine.dispose()


def test_archive_trading_engine_weekly_is_noop_without_output_and_runlog(tmp_path) -> None:
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

    state_path = tmp_path / "state.json"
    save_state(str(state_path), new_state("20260418"))
    cfg = TradeEngineConfig(
        state_path=str(state_path),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )

    with SessionLocal() as db:
        result = archive_trading_engine_weekly(
            db,
            config=cfg,
            now=datetime(2026, 4, 18, 6, 40),
        )
        row_count = db.query(TradingEngineArchive).count()

    assert result.status == "NOOP"
    assert result.archive_id is None
    assert row_count == 0
    assert state_path.exists()

    engine.dispose()


def test_finalize_day_no_longer_creates_backup_zip(tmp_path) -> None:
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = _SpyNotifier()
    bot = HybridTradingBot(object(), config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260418"
    bot.journal = TradeJournal(output_dir=cfg.output_dir, asof_date="20260418")

    summary_text = bot.finalize_day()

    assert summary_text is not None
    assert summary_text.startswith("[마감] 20260418")
    assert notifier.files == []
    assert list((tmp_path / "output").glob("*.zip")) == []
