from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.scripts.comfyui_drive_sync import (
    SyncConfig,
    _build_upload_name,
    _discover_candidates,
    _ensure_folder_id,
)


def make_config(tmp_path: Path, stable_age_sec: int = 15, folder_id: str | None = None) -> SyncConfig:
    return SyncConfig(
        output_dir=tmp_path / "output",
        state_path=tmp_path / "state.json",
        poll_interval_sec=30,
        stable_age_sec=stable_age_sec,
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
