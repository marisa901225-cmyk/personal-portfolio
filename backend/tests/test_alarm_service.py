import asyncio
import os
import sys
import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session

# 프로젝트 루트를 패스에 추가
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.append(PROJECT_ROOT)

from backend.core.db import SessionLocal
from backend.core.models import IncomingAlarm
from backend.services.alarm_service import AlarmService

async def run_processing():
    db = SessionLocal()
    try:
        await AlarmService.process_pending_alarms(db)
    finally:
        db.close()

@pytest.mark.integration
async def test_alarm_service():
    print("--- Starting Alarm Service Test ---")
    ts = datetime.now().strftime("%H%M%S")
    
    # 1. 테스트 알람 주입 (Legitimate alarm)
    print("1. Injecting test alarm...")
    test_text = f"[공지-{ts}] 서비스 정상 작동 확인을 위한 테스트 알림입니다."
    db = SessionLocal()
    test_alarm_id = None
    try:
        test_alarm = IncomingAlarm(
            raw_text=test_text,
            sender="테스터",
            app_name="TestApp",
            package="com.test.app",
            app_title="테스트 알림",
            status="pending",
            received_at=datetime.now(timezone.utc)
        )
        db.add(test_alarm)
        db.commit()
        test_alarm_id = test_alarm.id
        print(f"   Injected test alarm with ID: {test_alarm_id}")
    finally:
        db.close()

    # 2. 알람 처리 트리거
    print("2. Triggering alarm processing...")
    await run_processing()
    
    # 3. 결과 확인
    db = SessionLocal()
    try:
        alarm = db.query(IncomingAlarm).get(test_alarm_id)
        print(f"   Alarm status: {alarm.status}")
        print(f"   Alarm classification: {alarm.classification}")
        if alarm.status == "processed":
            print("✅ Legitimate alarm processed successfully!")
        else:
            print(f"❌ Unexpected status: {alarm.status}")
    finally:
        db.close()

    # 4. 스팸 테스트
    print("4. Injecting spam alarm...")
    spam_text = f"(광고) 최저가 보장! 지금 바로 클릭하세요. 무료 체험의 기회!-{ts}"
    db = SessionLocal()
    spam_id = None
    try:
        spam_alarm = IncomingAlarm(
            raw_text=spam_text,
            sender="광고업체",
            app_name="SpamApp",
            package="com.spam.app",
            app_title="스팸 알림",
            status="pending",
            received_at=datetime.now(timezone.utc)
        )
        db.add(spam_alarm)
        db.commit()
        spam_id = spam_alarm.id
        print(f"   Injected spam alarm with ID: {spam_id}")
    finally:
        db.close()

    print("5. Triggering alarm processing again...")
    await run_processing()
    
    db = SessionLocal()
    try:
        alarm = db.query(IncomingAlarm).get(spam_id)
        print(f"   Spam alarm status: {alarm.status}")
        print(f"   Spam alarm classification: {alarm.classification}")
        if alarm.status == "discarded":
            print("✅ Spam alarm discarded successfully!")
        else:
            print(f"❌ Spam alarm NOT discarded: {alarm.status}")
    finally:
        db.close()

    print("--- Test Finished ---")

if __name__ == "__main__":
    asyncio.run(test_alarm_service())

if __name__ == "__main__":
    asyncio.run(test_alarm_service())
