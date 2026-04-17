from __future__ import annotations

import asyncio
import errno
import html
import json
import logging
import os
import secrets
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from backend.core.env_paths import get_secrets_env_file
from backend.integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_AUTH_ROTATION_TELEGRAM_BOT_TYPE = "main"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


@dataclass(frozen=True)
class AuthSecretRotationConfig:
    enabled: bool = False
    interval_days: int = 60
    check_hour: int = 4
    check_minute: int = 17
    skip_initial_rotation: bool = True
    telegram_bot_type: str = _AUTH_ROTATION_TELEGRAM_BOT_TYPE
    restart_hint_services: str = "backend-api alarm-collector"
    state_path: Path = Path("backend/data/auth_secret_rotation_state.json")


def load_auth_secret_rotation_config_from_env() -> AuthSecretRotationConfig:
    state_path_raw = os.getenv(
        "BACKEND_AUTH_ROTATE_STATE_PATH",
        "backend/data/auth_secret_rotation_state.json",
    ).strip()
    restart_hint_services = (
        os.getenv("BACKEND_AUTH_ROTATE_RESTART_HINT_SERVICES", "backend-api alarm-collector").strip()
        or "backend-api alarm-collector"
    )
    return AuthSecretRotationConfig(
        enabled=_env_bool("BACKEND_AUTH_ROTATE_ENABLED", False),
        interval_days=_env_int("BACKEND_AUTH_ROTATE_INTERVAL_DAYS", 60, minimum=1, maximum=3650),
        check_hour=_env_int("BACKEND_AUTH_ROTATE_CHECK_HOUR", 4, minimum=0, maximum=23),
        check_minute=_env_int("BACKEND_AUTH_ROTATE_CHECK_MINUTE", 17, minimum=0, maximum=59),
        skip_initial_rotation=_env_bool("BACKEND_AUTH_ROTATE_SKIP_INITIAL", True),
        telegram_bot_type=_AUTH_ROTATION_TELEGRAM_BOT_TYPE,
        restart_hint_services=restart_hint_services,
        state_path=Path(state_path_raw).expanduser(),
    )


def _ensure_kst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def _format_dt(dt: datetime) -> str:
    return _ensure_kst(dt).isoformat(timespec="seconds")


def _parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _ensure_kst(datetime.fromisoformat(value))
    except ValueError:
        return None


def _read_state(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("auth secret rotation state read failed: %s", path, exc_info=True)
        return {}


def _atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    if mode is not None:
        tmp_path.chmod(mode)
    try:
        os.replace(tmp_path, path)
    except OSError as exc:
        if exc.errno not in {errno.EBUSY, errno.EXDEV}:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                logger.warning("failed to clean auth rotation temp file: %s", tmp_path, exc_info=True)
            raise

        logger.warning(
            "atomic replace unavailable for %s (errno=%s); falling back to direct write",
            path,
            exc.errno,
        )
        try:
            path.write_text(text, encoding="utf-8")
            if mode is not None:
                path.chmod(mode)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                logger.warning("failed to clean auth rotation temp file: %s", tmp_path, exc_info=True)


def _write_state(path: Path, payload: dict[str, object]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_text(path, text)


def _render_env_text(existing_text: str, updates: dict[str, str]) -> str:
    lines = existing_text.splitlines()
    replaced: set[str] = set()
    rendered: list[str] = []

    for line in lines:
        stripped = line.strip()
        export_prefix = ""
        candidate = stripped
        if stripped.startswith("export "):
            export_prefix = "export "
            candidate = stripped[len("export ") :]

        if not candidate or candidate.startswith("#") or "=" not in candidate:
            rendered.append(line)
            continue

        key, _ = candidate.split("=", 1)
        key = key.strip()
        if key in updates:
            indent = line[: len(line) - len(line.lstrip())]
            rendered.append(f"{indent}{export_prefix}{key}={updates[key]}")
            replaced.add(key)
            continue

        rendered.append(line)

    missing = [key for key in updates if key not in replaced]
    if missing:
        if rendered and rendered[-1].strip():
            rendered.append("")
        rendered.extend(f"{key}={updates[key]}" for key in missing)

    return "\n".join(rendered).rstrip() + "\n"


def update_env_assignments(path: Path, updates: dict[str, str]) -> None:
    existing_text = path.read_text(encoding="utf-8") if path.exists() else ""
    mode: int | None = None
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    new_text = _render_env_text(existing_text, updates)
    _atomic_write_text(path, new_text, mode=mode)


def generate_rotated_secret_values() -> dict[str, str]:
    return {
        "API_TOKEN": secrets.token_hex(32),
        "JWT_SECRET_KEY": secrets.token_hex(64),
    }


def _build_rotation_message(
    *,
    rotated_at: datetime,
    env_path: Path,
    interval_days: int,
    restart_hint_services: str,
) -> str:
    restart_command = f"docker compose up -d --force-recreate {restart_hint_services}".strip()
    return (
        "🔐 <b>백엔드 인증 비밀키 회전 완료</b>\n\n"
        f"- 시각: <code>{html.escape(_format_dt(rotated_at))}</code>\n"
        f"- 대상: <code>API_TOKEN</code>, <code>JWT_SECRET_KEY</code>\n"
        f"- 주기 기준: <code>{interval_days}일</code>\n"
        f"- env 파일: <code>{html.escape(str(env_path))}</code>\n\n"
        "다음 확인이 필요합니다.\n"
        "1. env 파일 변경분 확인\n"
        f"2. 서비스 재생성: <code>{html.escape(restart_command)}</code>\n"
        "3. 재생성 후 API 인증 동작 확인\n\n"
        "참고: <code>JWT_SECRET_KEY</code>는 재적용 후 기존 로그인 세션을 무효화합니다."
    )


def _send_rotation_notification(
    *,
    rotated_at: datetime,
    env_path: Path,
    config: AuthSecretRotationConfig,
) -> bool:
    message = _build_rotation_message(
        rotated_at=rotated_at,
        env_path=env_path,
        interval_days=config.interval_days,
        restart_hint_services=config.restart_hint_services,
    )
    try:
        return bool(asyncio.run(send_telegram_message(message, bot_type=config.telegram_bot_type)))
    except Exception:
        logger.warning("auth secret rotation telegram notify failed", exc_info=True)
        return False


def _seed_state_from_env_mtime(*, env_path: Path, state_path: Path) -> dict[str, object]:
    seeded_at = datetime.fromtimestamp(env_path.stat().st_mtime, tz=KST)
    payload = {
        "last_rotated_at": _format_dt(seeded_at),
        "last_seeded_at": _format_dt(datetime.now(KST)),
        "env_file": str(env_path),
        "seeded_from_env_mtime": True,
    }
    _write_state(state_path, payload)
    return {
        "status": "seeded",
        "env_file": str(env_path),
        "seeded_at": payload["last_rotated_at"],
    }


def rotate_backend_auth_secrets(
    *,
    config: AuthSecretRotationConfig | None = None,
    now: datetime | None = None,
    force: bool = False,
    notify: bool = True,
) -> dict[str, object]:
    cfg = config or load_auth_secret_rotation_config_from_env()
    current_time = _ensure_kst(now or datetime.now(KST))

    if not cfg.enabled and not force:
        return {"status": "disabled"}

    env_path = get_secrets_env_file()
    if not env_path.exists():
        raise FileNotFoundError(f"secrets env file not found: {env_path}")

    state = _read_state(cfg.state_path)
    last_rotated_at = _parse_dt(state.get("last_rotated_at"))

    if cfg.skip_initial_rotation and last_rotated_at is None and not force:
        return _seed_state_from_env_mtime(env_path=env_path, state_path=cfg.state_path)

    if not force and last_rotated_at is not None:
        next_rotation_at = last_rotated_at + timedelta(days=cfg.interval_days)
        if current_time < next_rotation_at:
            return {
                "status": "skipped",
                "env_file": str(env_path),
                "last_rotated_at": _format_dt(last_rotated_at),
                "next_rotation_at": _format_dt(next_rotation_at),
            }

    updates = generate_rotated_secret_values()
    update_env_assignments(env_path, updates)

    payload = {
        "env_file": str(env_path),
        "keys": sorted(updates),
        "last_rotated_at": _format_dt(current_time),
        "rotation_interval_days": cfg.interval_days,
        "telegram_bot_type": cfg.telegram_bot_type,
    }
    _write_state(cfg.state_path, payload)

    notified = False
    if notify:
        notified = _send_rotation_notification(
            rotated_at=current_time,
            env_path=env_path,
            config=cfg,
        )

    return {
        "status": "rotated",
        "env_file": str(env_path),
        "last_rotated_at": payload["last_rotated_at"],
        "notified": notified,
    }
