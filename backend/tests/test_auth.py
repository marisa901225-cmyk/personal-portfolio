import asyncio
import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from backend.core import auth
from backend.services.auth_secret_rotation import (
    AuthSecretRotationConfig,
    _atomic_write_text,
    rotate_backend_auth_secrets,
)


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._prev_token = auth.API_TOKEN

    def tearDown(self) -> None:
        auth.API_TOKEN = self._prev_token

    @staticmethod
    def _request(
        host: str,
        *,
        client_host: str = "1.2.3.4",
        forwarded_host: str | None = None,
        forwarded_for: str | None = None,
    ) -> Request:
        headers = [(b"host", host.encode("utf-8"))]
        if forwarded_host:
            headers.append((b"x-forwarded-host", forwarded_host.encode("utf-8")))
        if forwarded_for:
            headers.append((b"x-forwarded-for", forwarded_for.encode("utf-8")))
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": "/api/health",
                "raw_path": b"/api/health",
                "query_string": b"",
                "headers": headers,
                "client": (client_host, 12345),
                "server": ("testserver", 443),
            }
        )

    def test_verify_api_token_fails_when_unset_and_not_debug(self) -> None:
        auth.API_TOKEN = ""
        # ALLOW_NO_AUTH가 False이고 debug가 False일 때, 토큰이 없으면 503 에러 발생
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token(self._request("localhost"), None))
        self.assertEqual(context.exception.status_code, 503)

    def test_verify_api_token_rejects_invalid(self) -> None:
        auth.API_TOKEN = "secret"
        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token(self._request("localhost"), "invalid"))
        self.assertEqual(context.exception.status_code, 401)

    def test_tailnet_request_accepts_api_key_only(self) -> None:
        auth.API_TOKEN = "secret"

        asyncio.run(
            auth.verify_api_token(
                self._request("marisa-server.tail5c2348.ts.net", client_host="100.99.67.34"),
                "secret",
            )
        )

    def test_tailnet_request_accepts_jwt_only(self) -> None:
        auth.API_TOKEN = "secret"

        with patch("backend.core.auth.jwt.decode", return_value={"sub": "user-1"}):
            asyncio.run(
                auth.verify_api_token(
                    self._request("marisa-server.tail5c2348.ts.net", client_host="100.99.67.34"),
                    None,
                    authorization="Bearer jwt-token",
                )
            )

    def test_non_tailnet_request_rejects_api_key_only(self) -> None:
        auth.API_TOKEN = "secret"

        with self.assertRaises(HTTPException) as context:
            asyncio.run(auth.verify_api_token(self._request("public.example.com"), "secret"))

        self.assertEqual(context.exception.status_code, 401)
        self.assertIn("JWT required", str(context.exception.detail))

    def test_non_tailnet_request_accepts_jwt_only(self) -> None:
        auth.API_TOKEN = "secret"

        with patch("backend.core.auth.jwt.decode", return_value={"sub": "user-1"}):
            asyncio.run(
                auth.verify_api_token(
                    self._request("public.example.com"),
                    None,
                    authorization="Bearer jwt-token",
                )
            )

    def test_forwarded_host_cannot_enable_api_key_only_auth(self) -> None:
        auth.API_TOKEN = "secret"

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                auth.verify_api_token(
                    self._request(
                        "public.example.com",
                        forwarded_host="marisa-server.tail5c2348.ts.net",
                    ),
                    "secret",
                )
            )

        self.assertEqual(context.exception.status_code, 401)

    def test_loopback_proxy_uses_forwarded_client_ip(self) -> None:
        auth.API_TOKEN = "secret"

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                auth.verify_api_token(
                    self._request(
                        "marisa-server.tail5c2348.ts.net",
                        client_host="127.0.0.1",
                        forwarded_for="203.0.113.10",
                    ),
                    "secret",
                )
            )

        self.assertEqual(context.exception.status_code, 401)

    def test_non_tailnet_request_accepts_jwt_with_api_key(self) -> None:
        auth.API_TOKEN = "secret"

        with patch("backend.core.auth.jwt.decode", return_value={"sub": "user-1"}):
            asyncio.run(
                auth.verify_api_token(
                    self._request("public.example.com"),
                    "secret",
                    authorization="Bearer jwt-token",
                )
            )


def _rotation_config(
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
    config = _rotation_config(state_path, skip_initial_rotation=True)

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
    config = _rotation_config(state_path, skip_initial_rotation=False)
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
    config = _rotation_config(state_path, interval_days=60, skip_initial_rotation=False)

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
