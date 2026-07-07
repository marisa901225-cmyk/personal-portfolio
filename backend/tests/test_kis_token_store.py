from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch


def test_read_kis_token_record_does_not_refresh_two_hours_before_expiry() -> None:
    from backend.integrations.kis import token_store

    setting = SimpleNamespace(
        kis_token_encrypted="encrypted",
        kis_token_expires_at=datetime.now() + timedelta(hours=1, minutes=30),
    )

    with patch.object(token_store, "_get_or_create_setting", return_value=setting), patch.object(
        token_store, "_decrypt_token", return_value="token"
    ), patch.object(token_store, "trigger_async_refresh") as refresh_mock:
        token, expires_at = token_store.read_kis_token_record(slot=0, db=Mock())

    assert token == "token"
    assert expires_at == setting.kis_token_expires_at
    refresh_mock.assert_not_called()


def test_read_kis_token_record_refreshes_inside_one_hour_window() -> None:
    from backend.integrations.kis import token_store

    setting = SimpleNamespace(
        kis_token_encrypted="encrypted",
        kis_token_expires_at=datetime.now() + timedelta(minutes=45),
    )

    with patch.object(token_store, "_get_or_create_setting", return_value=setting), patch.object(
        token_store, "_decrypt_token", return_value="token"
    ), patch.object(token_store, "trigger_async_refresh") as refresh_mock:
        token, expires_at = token_store.read_kis_token_record(slot=0, db=Mock())

    assert token == "token"
    assert expires_at == setting.kis_token_expires_at
    refresh_mock.assert_called_once()
