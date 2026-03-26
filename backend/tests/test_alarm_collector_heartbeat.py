import json
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_heartbeat_endpoint_persists_state(tmp_path, monkeypatch):
    db_path = tmp_path / "heartbeat.db"
    state_path = tmp_path / "alarm_heartbeat_state.json"

    import backend.services.alarm.collector_app as collector_app
    from backend.services.alarm.collector_app import app

    monkeypatch.setattr(collector_app, "API_TOKEN", "test_token")
    monkeypatch.setattr(collector_app, "DB_PATH", str(db_path))
    monkeypatch.setattr(collector_app, "CURRENT_HEARTBEAT_STATE_PATH", str(state_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/heartbeat",
            json={
                "device_id": "phone-main",
                "ping_target": "100.64.0.10",
                "sent_at": str(datetime.now().timestamp()),
                "battery": "91",
                "charging": "false",
                "network": "WIFI",
            },
            headers={"Authorization": "Bearer test_token"},
        )

    assert response.status_code == 200
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT device_id, ping_target, battery, alert_sent FROM device_heartbeats ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row == ("phone-main", "100.64.0.10", "91", 0)
    snapshot = json.loads(state_path.read_text(encoding="utf-8"))
    assert snapshot["snapshot_mode"] == "current_only"
    assert snapshot["devices"]["phone-main"]["ping_target"] == "100.64.0.10"


@pytest.mark.asyncio
async def test_heartbeat_silence_uses_ping_result(tmp_path, monkeypatch):
    db_path = tmp_path / "heartbeat.db"
    state_path = tmp_path / "alarm_heartbeat_state.json"

    import backend.services.alarm.collector_app as collector_app

    monkeypatch.setattr(collector_app, "DB_PATH", str(db_path))
    monkeypatch.setattr(collector_app, "CURRENT_HEARTBEAT_STATE_PATH", str(state_path))
    collector_app.ensure_heartbeat_table(str(db_path))

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO device_heartbeats (
            device_id, tailscale_name, ping_target, sent_at, received_at, battery, charging, network, ping_ok, alert_sent
        ) VALUES (?, ?, ?, ?, datetime('now'), ?, ?, ?, NULL, 0)
        """,
        (
            "phone-main",
            "phone-main",
            "100.64.0.10",
            (datetime.now() - timedelta(minutes=20)).isoformat(sep=" ", timespec="seconds"),
            "91",
            "false",
            "WIFI",
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("HEARTBEAT_SILENCE_ALERT_SECONDS", "900")
    monkeypatch.setattr(
        collector_app,
        "_ping_device_target",
        AsyncMock(return_value=True),
    )

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.integrations.telegram.send_telegram_message", mock_send)

    sent = await collector_app.evaluate_heartbeat_silence(now=datetime.now())

    assert sent is True
    message = mock_send.await_args.args[0]
    assert "Tasker" in message
    assert "응답 중입니다" in message
    conn = sqlite3.connect(db_path)
    updated = conn.execute(
        "SELECT ping_ok, alert_sent FROM device_heartbeats ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert updated == (1, 1)
    snapshot = json.loads(state_path.read_text(encoding="utf-8"))
    assert snapshot["devices"]["phone-main"]["ping_ok"] is True
    assert snapshot["devices"]["phone-main"]["alert_sent"] is True
