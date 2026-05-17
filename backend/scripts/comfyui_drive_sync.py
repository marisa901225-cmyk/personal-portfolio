from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from backend.core.env_paths import get_project_env_files
from backend.services.google_drive_client import GoogleDriveService


logger = logging.getLogger(__name__)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@dataclass(frozen=True)
class SyncConfig:
    output_dir: Path
    state_path: Path
    poll_interval_sec: int
    stable_age_sec: int
    folder_name: str
    folder_id: str | None
    client_id: str
    client_secret: str
    refresh_token: str


def _load_env() -> None:
    for env_path in get_project_env_files():
        load_dotenv(env_path)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r. Falling back to %s.", name, raw, default)
        return default


def _build_config() -> SyncConfig:
    output_dir = Path(os.getenv("COMFYUI_OUTPUT_DIR", "/comfyui-output")).resolve()
    state_path = Path(
        os.getenv("COMFYUI_GDRIVE_SYNC_STATE_PATH", "/app/backend/data/comfyui_gdrive_sync_state.json")
    ).resolve()
    folder_name = os.getenv("COMFYUI_GDRIVE_FOLDER_NAME", "Comfyui 이미지").strip() or "Comfyui 이미지"
    folder_id = os.getenv("COMFYUI_GDRIVE_FOLDER_ID", "").strip() or None
    client_id = os.getenv("GOOGLE_DRIVE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_DRIVE_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_DRIVE_REFRESH_TOKEN", "").strip()
    poll_interval_sec = max(5, _env_int("COMFYUI_GDRIVE_POLL_INTERVAL_SEC", 30))
    stable_age_sec = max(5, _env_int("COMFYUI_GDRIVE_STABLE_AGE_SEC", 15))

    missing = [
        name
        for name, value in (
            ("GOOGLE_DRIVE_CLIENT_ID", client_id),
            ("GOOGLE_DRIVE_CLIENT_SECRET", client_secret),
            ("GOOGLE_DRIVE_REFRESH_TOKEN", refresh_token),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing Google Drive credentials: {', '.join(missing)}")

    return SyncConfig(
        output_dir=output_dir,
        state_path=state_path,
        poll_interval_sec=poll_interval_sec,
        stable_age_sec=stable_age_sec,
        folder_name=folder_name,
        folder_id=folder_id,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )


def _load_state(state_path: Path) -> dict[str, dict[str, int]]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read sync state from %s: %s", state_path, exc)
        return {}


def _save_state(state_path: Path, state: dict[str, dict[str, int]]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _discover_candidates(config: SyncConfig, state: dict[str, dict[str, int]]) -> list[Path]:
    if not config.output_dir.exists():
        logger.warning("ComfyUI output directory does not exist yet: %s", config.output_dir)
        return []

    now = time.time()
    candidates: list[Path] = []
    for path in sorted(config.output_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue

        stat = path.stat()
        if now - stat.st_mtime < config.stable_age_sec:
            continue

        rel = path.relative_to(config.output_dir).as_posix()
        previous = state.get(rel)
        current = {
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
        if previous == current:
            continue
        candidates.append(path)
    return candidates


def _ensure_folder_id(config: SyncConfig, access_token: str) -> str | None:
    if config.folder_id:
        return config.folder_id

    folder_id = GoogleDriveService.get_folder_id_by_name(config.folder_name, access_token)
    if folder_id:
        return folder_id

    logger.info("Google Drive folder '%s' not found. Creating it...", config.folder_name)
    return GoogleDriveService.create_folder(config.folder_name, access_token)


def _build_upload_name(config: SyncConfig, path: Path) -> str:
    rel = path.relative_to(config.output_dir).as_posix()
    return rel.replace("/", "__")


def run_sync_loop() -> int:
    _load_env()
    config = _build_config()

    logging.basicConfig(
        level=os.getenv("COMFYUI_GDRIVE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Starting ComfyUI Google Drive sync for %s", config.output_dir)
    state = _load_state(config.state_path)

    while True:
        try:
            candidates = _discover_candidates(config, state)
            if candidates:
                access_token = GoogleDriveService.get_access_token(
                    config.client_id,
                    config.client_secret,
                    config.refresh_token,
                )
                if not access_token:
                    logger.error("Failed to refresh Google Drive access token.")
                else:
                    folder_id = _ensure_folder_id(config, access_token)
                    if not folder_id:
                        logger.error("Failed to resolve Google Drive folder id for '%s'.", config.folder_name)
                    else:
                        for path in candidates:
                            rel = path.relative_to(config.output_dir).as_posix()
                            logger.info("Uploading ComfyUI image: %s", rel)
                            if GoogleDriveService.upload_file(
                                str(path),
                                folder_id,
                                access_token,
                                upload_name=_build_upload_name(config, path),
                            ):
                                stat = path.stat()
                                state[rel] = {
                                    "size": int(stat.st_size),
                                    "mtime_ns": int(stat.st_mtime_ns),
                                }
                                _save_state(config.state_path, state)
                            else:
                                logger.error("Upload failed for %s", rel)
            time.sleep(config.poll_interval_sec)
        except KeyboardInterrupt:
            logger.info("Stopping ComfyUI Google Drive sync.")
            return 0
        except Exception:
            logger.exception("Unexpected error in ComfyUI Google Drive sync loop")
            time.sleep(config.poll_interval_sec)


def main() -> int:
    try:
        return run_sync_loop()
    except Exception as exc:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        logger.error("ComfyUI Google Drive sync failed to start: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
