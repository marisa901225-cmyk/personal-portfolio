import os
import pytest
import sqlite3
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

# 테스트용 DB 경로 설정 (conftest.py 기준)
from backend.tests.conftest import TEST_DB_PATH


def _clear_incoming_alarms(db_path: str) -> None:
    with sqlite3.connect(db_path, timeout=5) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("DELETE FROM incoming_alarms")

@pytest.fixture(scope="module")
def setup_test_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    
    # 디렉토리가 없으면 생성 (backend/tests에서 실행될 경우 대비)
    os.makedirs(os.path.dirname(TEST_DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS incoming_alarms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            raw_text TEXT,
            masked_text TEXT,
            sender TEXT,
            app_name TEXT,
            package TEXT,
            app_title TEXT,
            conversation TEXT,
            status TEXT DEFAULT 'pending',
            received_at DATETIME
        )
    """)
    conn.commit()
    conn.close()
    yield TEST_DB_PATH
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

@pytest.mark.asyncio
async def test_collect_alarm_integrated(setup_test_db, monkeypatch):
    db_path = setup_test_db
    monkeypatch.setenv("API_TOKEN", "test_token")
    monkeypatch.setenv("ALARM_DEDUP_WINDOW_SECONDS", "1800")
    
    # 모킹 후 임포트
    import backend.services.alarm.collector_app as collector_app
    from backend.services.alarm.collector_app import app
    monkeypatch.setattr(collector_app, "DB_PATH", db_path)
    monkeypatch.setattr(collector_app, "API_TOKEN", "test_token")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": "Bearer test_token"}
        payload = {
            "raw_text": "Integrated Test Notification",
            "sender": "Tester",
            "app_name": "TestApp"
        }

        # 1. 첫 번째 알람 수신 테스트
        response = await ac.post("/webhook", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        first_id = response.json()["id"]

        # 2. 중복 알람 테스트 (dedupe window 이내 동일 시그니처)
        response_dup = await ac.post("/webhook", json=payload, headers=headers)
        assert response_dup.status_code == 200
        assert response_dup.json()["status"] == "skipped"
        assert response_dup.json()["reason"] == "duplicate"

        # 3. DB 저장 결과 확인
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT raw_text FROM incoming_alarms WHERE id = ?", (first_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "Integrated Test Notification"
        conn.close()


@pytest.mark.asyncio
async def test_collect_alarm_not_deduped_after_window_expires(setup_test_db, monkeypatch):
    db_path = setup_test_db
    monkeypatch.setenv("API_TOKEN", "test_token")
    # 테스트 가속: dedupe window 3초
    monkeypatch.setenv("ALARM_DEDUP_WINDOW_SECONDS", "3")

    import backend.services.alarm.collector_app as collector_app
    from backend.services.alarm.collector_app import app
    monkeypatch.setattr(collector_app, "DB_PATH", db_path)
    monkeypatch.setattr(collector_app, "API_TOKEN", "test_token")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        headers = {"Authorization": "Bearer test_token"}
        payload = {
            "raw_text": "Window Expire Notification",
            "sender": "Tester",
            "app_name": "TestApp",
            "package": "com.test.app",
            "app_title": "Title",
            "conversation": "Conv",
        }

        first = await ac.post("/webhook", json=payload, headers=headers)
        assert first.status_code == 200
        assert first.json()["status"] == "ok"

        # 첫 알림을 과거 시각으로 옮겨 dedupe window 밖으로 보낸다.
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            "UPDATE incoming_alarms SET received_at = datetime('now', '-10 seconds') WHERE id = ?",
            (first.json()["id"],),
        )
        conn.commit()
        conn.close()

        second = await ac.post("/webhook", json=payload, headers=headers)
        assert second.status_code == 200
        assert second.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_collect_alarm_auth_failure(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test_token")
    from backend.services.alarm.collector_app import app
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 토큰 오류
        headers = {"Authorization": "Bearer wrong_token"}
        response = await ac.post("/webhook", json={"raw_text": "test"}, headers=headers)
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_alarm_silence_alert_sent_once_until_new_alarm(setup_test_db, monkeypatch):
    db_path = setup_test_db
    _clear_incoming_alarms(db_path)
    monkeypatch.setenv("ALARM_SILENCE_ALERT_SECONDS", "1800")
    monkeypatch.setenv("HEARTBEAT_SILENCE_ALERT_SECONDS", "900")
    # Keep legacy behavior for this test (always active window).
    monkeypatch.setenv("ALARM_SILENCE_ACTIVE_WINDOW", "00:00-24:00")

    import backend.services.alarm.collector_app as collector_app

    collector_app.ensure_heartbeat_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM device_heartbeats")
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

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "backend.integrations.telegram.send_telegram_message",
        mock_send,
    )
    monkeypatch.setattr(
        collector_app,
        "_ping_device_target",
        AsyncMock(return_value=False),
    )

    stale_time = datetime.now() - timedelta(minutes=31)

    state = {
        "startup_at": datetime.now(),
        "last_alarm_received_at": stale_time,
        "alert_sent": False,
    }

    first = await collector_app.evaluate_alarm_silence(state, db_path, now=datetime.now())
    second = await collector_app.evaluate_alarm_silence(state, db_path, now=datetime.now())

    assert first is True
    assert second is False
    assert mock_send.await_count == 1

    state["last_alarm_received_at"] = datetime.now()
    state["alert_sent"] = False

    third = await collector_app.evaluate_alarm_silence(
        state,
        db_path,
        now=datetime.now() + timedelta(minutes=31),
    )
    assert third is True
    assert mock_send.await_count == 2


@pytest.mark.asyncio
async def test_alarm_silence_uses_portfolio_db_as_secondary_reference(setup_test_db, monkeypatch):
    db_path = setup_test_db
    _clear_incoming_alarms(db_path)
    monkeypatch.setenv("ALARM_SILENCE_ALERT_SECONDS", "1800")
    monkeypatch.setenv("HEARTBEAT_SILENCE_ALERT_SECONDS", "900")
    monkeypatch.setenv("ALARM_SILENCE_ACTIVE_WINDOW", "00:00-24:00")

    import backend.services.alarm.collector_app as collector_app
    now = datetime(2026, 3, 10, 12, 0, 0)

    collector_app.ensure_heartbeat_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM device_heartbeats")
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
            (now - timedelta(minutes=20)).isoformat(sep=" ", timespec="seconds"),
            "91",
            "false",
            "WIFI",
        ),
    )
    conn.commit()
    conn.close()

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.integrations.telegram.send_telegram_message", mock_send)
    monkeypatch.setattr(
        collector_app,
        "_ping_device_target",
        AsyncMock(return_value=False),
    )

    recent_alarm_at = now - timedelta(minutes=5)

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO incoming_alarms (
            raw_text, masked_text, sender, app_name, package, app_title, conversation, status, received_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            "secondary reference alarm",
            "secondary reference alarm",
            "tester",
            "TestApp",
            "com.test.app",
            "Title",
            "Conv",
            recent_alarm_at.isoformat(sep=" ", timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()

    state = {
        "startup_at": now - timedelta(hours=1),
        "last_alarm_received_at": now - timedelta(minutes=40),
        "alert_sent": True,
    }

    sent = await collector_app.evaluate_alarm_silence(state, db_path, now=now)

    assert sent is False
    assert mock_send.await_count == 0
    assert state["last_alarm_received_at"] == recent_alarm_at
    assert state["alert_sent"] is False


@pytest.mark.asyncio
async def test_alarm_silence_suppressed_outside_active_window(setup_test_db, monkeypatch):
    db_path = setup_test_db
    _clear_incoming_alarms(db_path)
    monkeypatch.setenv("ALARM_SILENCE_ALERT_SECONDS", "1800")
    monkeypatch.setenv("ALARM_SILENCE_ACTIVE_WINDOW", "07:00-23:00")

    import backend.services.alarm.collector_app as collector_app

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.integrations.telegram.send_telegram_message", mock_send)

    now = datetime(2026, 3, 9, 2, 0, 0)
    state = {
        "startup_at": now,
        "last_alarm_received_at": datetime(2026, 3, 8, 22, 0, 0),
        "alert_sent": False,
    }

    sent = await collector_app.evaluate_alarm_silence(state, db_path, now=now)
    assert sent is False
    assert mock_send.await_count == 0


@pytest.mark.asyncio
async def test_alarm_silence_measures_from_window_start(setup_test_db, monkeypatch):
    db_path = setup_test_db
    _clear_incoming_alarms(db_path)
    monkeypatch.setenv("ALARM_SILENCE_ALERT_SECONDS", "1800")
    monkeypatch.setenv("HEARTBEAT_SILENCE_ALERT_SECONDS", "900")
    monkeypatch.setenv("ALARM_SILENCE_ACTIVE_WINDOW", "07:00-23:00")

    import backend.services.alarm.collector_app as collector_app

    collector_app.ensure_heartbeat_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM device_heartbeats")
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
            datetime(2026, 3, 9, 7, 10, 0).isoformat(sep=" ", timespec="seconds"),
            "91",
            "false",
            "WIFI",
        ),
    )
    conn.commit()
    conn.close()

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.integrations.telegram.send_telegram_message", mock_send)
    monkeypatch.setattr(
        collector_app,
        "_ping_device_target",
        AsyncMock(return_value=False),
    )

    state = {
        "startup_at": datetime(2026, 3, 9, 7, 0, 0),
        "last_alarm_received_at": datetime(2026, 3, 8, 22, 0, 0),
        "alert_sent": False,
    }

    # 07:05 -> 5 minutes since active window start -> no alert
    early = await collector_app.evaluate_alarm_silence(
        state,
        db_path,
        now=datetime(2026, 3, 9, 7, 5, 0),
    )
    assert early is False
    assert mock_send.await_count == 0

    # 07:35 -> 35 minutes since active window start -> alert
    late = await collector_app.evaluate_alarm_silence(
        state,
        db_path,
        now=datetime(2026, 3, 9, 7, 35, 0),
    )
    assert late is True
    assert mock_send.await_count == 1


@pytest.mark.asyncio
async def test_alarm_silence_suppressed_when_heartbeat_ping_succeeds(setup_test_db, monkeypatch):
    db_path = setup_test_db
    _clear_incoming_alarms(db_path)
    monkeypatch.setenv("ALARM_SILENCE_ALERT_SECONDS", "1800")
    monkeypatch.setenv("HEARTBEAT_SILENCE_ALERT_SECONDS", "900")
    monkeypatch.setenv("ALARM_SILENCE_ACTIVE_WINDOW", "00:00-24:00")

    import backend.services.alarm.collector_app as collector_app

    collector_app.ensure_heartbeat_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM device_heartbeats")
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
            (datetime(2026, 3, 10, 12, 0, 0) - timedelta(minutes=20)).isoformat(sep=" ", timespec="seconds"),
            "91",
            "false",
            "WIFI",
        ),
    )
    conn.commit()
    conn.close()

    mock_send = AsyncMock(return_value=True)
    monkeypatch.setattr("backend.integrations.telegram.send_telegram_message", mock_send)
    monkeypatch.setattr(
        collector_app,
        "_ping_device_target",
        AsyncMock(return_value=True),
    )

    state = {
        "startup_at": datetime(2026, 3, 10, 11, 0, 0),
        "last_alarm_received_at": datetime(2026, 3, 10, 11, 20, 0),
        "alert_sent": False,
    }

    sent = await collector_app.evaluate_alarm_silence(
        state,
        db_path,
        now=datetime(2026, 3, 10, 12, 0, 0),
    )

    assert sent is False
    assert mock_send.await_count == 0
