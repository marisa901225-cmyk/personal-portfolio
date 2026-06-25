from pathlib import Path

from backend.services.alarm import llm_refiner


def test_cleanup_oversized_llm_draft_logs_removes_rotated_logs_first(tmp_path: Path) -> None:
    log_path = tmp_path / "llm_drafts.jsonl"
    rotated_path = tmp_path / "llm_drafts.jsonl.1"
    log_path.write_text("current", encoding="utf-8")
    rotated_path.write_text("rotated-data", encoding="utf-8")

    deleted = llm_refiner._cleanup_oversized_llm_draft_logs(log_path, max_bytes=10)

    assert deleted == 1
    assert log_path.exists()
    assert not rotated_path.exists()


def test_cleanup_oversized_llm_draft_logs_removes_current_when_still_too_large(tmp_path: Path) -> None:
    log_path = tmp_path / "llm_drafts.jsonl"
    log_path.write_text("current-data", encoding="utf-8")

    deleted = llm_refiner._cleanup_oversized_llm_draft_logs(log_path, max_bytes=5)

    assert deleted == 1
    assert not log_path.exists()


def test_dump_llm_draft_restarts_file_after_size_cap(tmp_path: Path, monkeypatch) -> None:
    log_path = tmp_path / "llm_drafts.jsonl"
    log_path.write_bytes(b"x" * (1024 * 1024 + 1))
    monkeypatch.setattr(llm_refiner, "DEBUG_LLM_DRAFT", True)
    monkeypatch.setattr(llm_refiner, "LLM_DRAFT_LOG_PATH", str(log_path))
    monkeypatch.setattr(llm_refiner, "LLM_DRAFT_LOG_MAX_MB", 1)

    llm_refiner.dump_llm_draft("test", "fresh draft")

    assert log_path.exists()
    assert log_path.stat().st_size < 1024 * 1024
    assert "fresh draft" in log_path.read_text(encoding="utf-8")
