from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.scripts.comfyui_drive_sync import (
    SyncConfig,
    _build_upload_name,
    _cleanup_local_files,
    _discover_candidates,
    _ensure_folder_id,
    _needs_cleanup,
)


def make_config(tmp_path: Path, stable_age_sec: int = 15, folder_id: str | None = None) -> SyncConfig:
    return SyncConfig(
        output_dir=tmp_path / "output",
        state_path=tmp_path / "state.json",
        poll_interval_sec=30,
        stable_age_sec=stable_age_sec,
        max_local_bytes=1_073_741_824,
        folder_name="Comfyui 이미지",
        folder_id=folder_id,
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
    )


def test_discover_candidates_only_returns_stable_new_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    old_image = output_dir / "old.png"
    new_image = output_dir / "new.webp"
    text_file = output_dir / "note.txt"

    old_image.write_bytes(b"old")
    new_image.write_bytes(b"new")
    text_file.write_text("ignore", encoding="utf-8")

    monkeypatch.setattr("backend.scripts.comfyui_drive_sync.time.time", lambda: 1_000)
    os.utime(old_image, (970, 970))
    os.utime(new_image, (995, 995))
    os.utime(text_file, (970, 970))

    config = make_config(tmp_path, stable_age_sec=15)
    discovered = _discover_candidates(config, state={})

    assert discovered == [old_image]


def test_discover_candidates_skips_already_synced_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    image = output_dir / "same.png"
    image.write_bytes(b"same")

    monkeypatch.setattr("backend.scripts.comfyui_drive_sync.time.time", lambda: 1_000)
    os.utime(image, (900, 900))
    stat = image.stat()

    config = make_config(tmp_path)
    state = {"same.png": {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}}

    assert _discover_candidates(config, state=state) == []


def test_ensure_folder_id_uses_existing_folder_id() -> None:
    config = SyncConfig(
        output_dir=Path("/tmp/output"),
        state_path=Path("/tmp/state.json"),
        poll_interval_sec=30,
        stable_age_sec=15,
        max_local_bytes=1_073_741_824,
        folder_name="Comfyui 이미지",
        folder_id="existing-folder",
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
    )

    assert _ensure_folder_id(config, "token") == "existing-folder"


def test_build_upload_name_flattens_nested_path(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    nested = config.output_dir / "2026-05-18" / "image.png"

    assert _build_upload_name(config, nested) == "2026-05-18__image.png"


def test_needs_cleanup_when_total_exceeds_limit(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.output_dir.mkdir()
    image = config.output_dir / "image.png"
    image.write_bytes(b"x" * 12)
    config = SyncConfig(
        output_dir=config.output_dir,
        state_path=config.state_path,
        poll_interval_sec=config.poll_interval_sec,
        stable_age_sec=config.stable_age_sec,
        max_local_bytes=10,
        folder_name=config.folder_name,
        folder_id=config.folder_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
        refresh_token=config.refresh_token,
    )

    assert _needs_cleanup(config, {"image.png": {"size": 12, "mtime_ns": image.stat().st_mtime_ns}}) is True


def test_cleanup_deletes_oldest_drive_backed_files_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(tmp_path)
    config.output_dir.mkdir()
    old_image = config.output_dir / "old.png"
    new_image = config.output_dir / "new.png"
    unsynced_image = config.output_dir / "unsynced.png"
    old_image.write_bytes(b"123456")
    new_image.write_bytes(b"abcdef")
    unsynced_image.write_bytes(b"zzzzzz")
    os.utime(old_image, (100, 100))
    os.utime(new_image, (200, 200))
    os.utime(unsynced_image, (50, 50))

    config = SyncConfig(
        output_dir=config.output_dir,
        state_path=config.state_path,
        poll_interval_sec=config.poll_interval_sec,
        stable_age_sec=config.stable_age_sec,
        max_local_bytes=7,
        folder_name=config.folder_name,
        folder_id=config.folder_id,
        client_id=config.client_id,
        client_secret=config.client_secret,
        refresh_token=config.refresh_token,
    )
    state = {
        "old.png": {"size": int(old_image.stat().st_size), "mtime_ns": int(old_image.stat().st_mtime_ns)},
        "new.png": {"size": int(new_image.stat().st_size), "mtime_ns": int(new_image.stat().st_mtime_ns)},
    }

    monkeypatch.setattr(
        "backend.scripts.comfyui_drive_sync.GoogleDriveService.file_exists_in_folder",
        lambda file_name, folder_id, access_token: file_name in {"old.png", "new.png"},
    )

    _cleanup_local_files(config, state, "folder-id", "token")

    assert old_image.exists() is False
    assert new_image.exists() is True
    assert unsynced_image.exists() is True
