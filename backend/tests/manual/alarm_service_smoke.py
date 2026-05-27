from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from backend.core.db import SessionLocal
from backend.core.models import IncomingAlarm
from backend.services.alarm_service import AlarmService


async def run_processing() -> None:
    db = SessionLocal()
    try:
        await AlarmService.process_pending_alarms(db)
    finally:
        db.close()


async def run_demo() -> None:
    ts = datetime.now().strftime("%H%M%S")

    db = SessionLocal()
    try:
        test_alarm = IncomingAlarm(
            raw_text=f"[공지-{ts}] 서비스 정상 작동 확인을 위한 테스트 알림입니다.",
            sender="테스터",
            app_name="TestApp",
            package="com.test.app",
            app_title="테스트 알림",
            status="pending",
            received_at=datetime.now(timezone.utc),
        )
        db.add(test_alarm)
        db.commit()
        test_alarm_id = test_alarm.id
    finally:
        db.close()

    await run_processing()

    db = SessionLocal()
    try:
        alarm = db.query(IncomingAlarm).get(test_alarm_id)
        print(f"Alarm status: {alarm.status}, classification: {alarm.classification}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(run_demo())
