from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.services.auth_secret_rotation import (
    AuthSecretRotationConfig,
    _atomic_write_text,
    rotate_backend_auth_secrets,
)


def _config(
    state_path: Path,
    *,
    enabled: bool = True,
    interval_days: int = 60,
    skip_initial_rotation: bool = True,
) -> AuthSecretRotationConfig:
    return AuthSecretRotationConfig(
        enabled=enabled,
        interval_days=interval_days,
        check_hour=4,
        check_minute=17,
        skip_initial_rotation=skip_initial_rotation,
        telegram_bot_type="main",
        restart_hint_services="backend-api alarm-collector",
        state_path=state_path,
    )


def test_rotate_backend_auth_secrets_seeds_from_env_mtime_on_first_run(tmp_path):
    env_path = tmp_path / "secrets.env"
    env_path.write_text("API_TOKEN=old-token\nJWT_SECRET_KEY=old-secret\n", encoding="utf-8")
    seeded_dt = datetime(2026, 4, 17, 14, 20, 0)
    seeded_ts = seeded_dt.timestamp()
    os.utime(env_path, (seeded_ts, seeded_ts))

    state_path = tmp_path / "state.json"
    config = _config(state_path, skip_initial_rotation=True)

    with patch("backend.services.auth_secret_rotation.get_secrets_env_file", return_value=env_path), patch(
        "backend.services.auth_secret_rotation._send_rotation_notification"
    ) as notify_mock:
        result = rotate_backend_auth_secrets(
            config=config,
            now=datetime(2026, 4, 18, 4, 17, 0),
        )

    assert result["status"] == "seeded"
    assert env_path.read_text(encoding="utf-8") == "API_TOKEN=old-token\nJWT_SECRET_KEY=old-secret\n"
    notify_mock.assert_not_called()

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["seeded_from_env_mtime"] is True
    assert payload["last_rotated_at"].startswith("2026-04-17T14:20:00")


def test_rotate_backend_auth_secrets_updates_env_state_and_notifies(tmp_path):
    env_path = tmp_path / "secrets.env"
    env_path.write_text("# secrets\nAPI_TOKEN=old-token\nOTHER=value\n", encoding="utf-8")

    state_path = tmp_path / "state.json"
    config = _config(state_path, skip_initial_rotation=False)
    now = datetime(2026, 6, 1, 4, 17, 0)

    with patch("backend.services.auth_secret_rotation.get_secrets_env_file", return_value=env_path), patch(
        "backend.services.auth_secret_rotation.generate_rotated_secret_values",
        return_value={"API_TOKEN": "new-token", "JWT_SECRET_KEY": "new-secret"},
    ), patch(
        "backend.services.auth_secret_rotation._send_rotation_notification",
        return_value=True,
    ) as notify_mock:
        result = rotate_backend_auth_secrets(
            config=config,
            now=now,
        )

    assert result == {
        "status": "rotated",
        "env_file": str(env_path),
        "last_rotated_at": "2026-06-01T04:17:00+09:00",
        "notified": True,
    }
    text = env_path.read_text(encoding="utf-8")
    assert "# secrets" in text
    assert "API_TOKEN=new-token" in text
    assert "JWT_SECRET_KEY=new-secret" in text
    assert "OTHER=value" in text

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["keys"] == ["API_TOKEN", "JWT_SECRET_KEY"]
    assert payload["last_rotated_at"] == "2026-06-01T04:17:00+09:00"
    notify_mock.assert_called_once()


def test_rotate_backend_auth_secrets_skips_until_interval_elapses(tmp_path):
    env_path = tmp_path / "secrets.env"
    env_path.write_text("API_TOKEN=still-old\nJWT_SECRET_KEY=still-old\n", encoding="utf-8")

    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_rotated_at": "2026-06-01T04:17:00+09:00",
            }
        ),
        encoding="utf-8",
    )
    config = _config(state_path, interval_days=60, skip_initial_rotation=False)

    with patch("backend.services.auth_secret_rotation.get_secrets_env_file", return_value=env_path), patch(
        "backend.services.auth_secret_rotation._send_rotation_notification"
    ) as notify_mock:
        result = rotate_backend_auth_secrets(
            config=config,
            now=datetime(2026, 6, 15, 4, 17, 0),
        )

    assert result["status"] == "skipped"
    assert result["last_rotated_at"] == "2026-06-01T04:17:00+09:00"
    assert result["next_rotation_at"] == "2026-07-31T04:17:00+09:00"
    assert env_path.read_text(encoding="utf-8") == "API_TOKEN=still-old\nJWT_SECRET_KEY=still-old\n"
    notify_mock.assert_not_called()


def test_atomic_write_text_falls_back_when_replace_is_busy(tmp_path):
    target = tmp_path / "mounted.env"
    target.write_text("old\n", encoding="utf-8")

    replace_calls = {"count": 0}

    def busy_replace(src, dst):
        replace_calls["count"] += 1
        raise OSError(16, "Device or resource busy", str(dst))

    with patch("backend.services.auth_secret_rotation.os.replace", side_effect=busy_replace):
        _atomic_write_text(target, "new\n")

    assert replace_calls["count"] == 1
    assert target.read_text(encoding="utf-8") == "new\n"
