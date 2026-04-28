from __future__ import annotations

from backend.core.models import Setting
from backend.services import settings_service


def test_to_settings_read_masks_kis_secrets(monkeypatch):
    monkeypatch.setattr(settings_service, "decrypt_kis_secret", lambda value: value)

    setting = Setting(
        user_id=1,
        kis_app="abcd1234",
        kis_sec="super-secret-value",
        kis_acct_stock="12345678",
        kis_prod="01",
        kis_htsid="hts-user-01",
        kis_agent="agent-value",
        kis_prod_url="https://example.com/prod",
    )

    result = settings_service.to_settings_read(setting)

    assert result.kis_app == "ab***34"
    assert result.kis_sec == "su***ue"
    assert result.kis_acct_stock == "12***78"
    assert result.kis_prod == "***"
    assert result.kis_htsid == "ht***01"
    assert result.kis_agent == "ag***ue"
    assert result.kis_prod_url == "https://example.com/prod"
