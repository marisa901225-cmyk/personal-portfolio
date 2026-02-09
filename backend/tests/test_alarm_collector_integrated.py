import os
import pytest
import sqlite3
from httpx import AsyncClient, ASGITransport
from datetime import datetime

# 테스트용 DB 경로 설정 (conftest.py 기준)
from tests.conftest import TEST_DB_PATH

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

        # 2. 중복 알람 테스트 (3초 이내 동일 내용)
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
async def test_collect_alarm_auth_failure(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test_token")
    from backend.services.alarm.collector_app import app
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 토큰 오류
        headers = {"Authorization": "Bearer wrong_token"}
        response = await ac.post("/webhook", json={"raw_text": "test"}, headers=headers)
        assert response.status_code == 403
