from __future__ import annotations

from backend.core.db import SessionLocal
from backend.core.models import IncomingAlarm
from backend.core.time_utils import utcnow


def create_test_alarms() -> None:
    db = SessionLocal()
    try:
        test_alarms = [
            {
                "sender": "홍길동",
                "app_name": "카카오톡",
                "raw_text": "내일 2시에 강남역에서 만날까? 점심 먹으면서 프로젝트 이야기하자!",
                "masked_text": "내일 2시에 강남역에서 만날까? 점심 먹으면서 프로젝트 이야기하자!",
            },
            {
                "sender": "김철수",
                "app_name": "카카오톡",
                "raw_text": "회의 자료 확인 부탁드립니다. 내일까지 피드백 주세요~",
                "masked_text": "회의 자료 확인 부탁드립니다. 내일까지 피드백 주세요~",
            },
            {
                "sender": "리꼬타",
                "app_name": "문피아",
                "raw_text": "군필 미소녀가 방송을 너무 잘함 - 125화 업로드 완료!",
                "masked_text": "군필 미소녀가 방송을 너무 잘함 - 125화 업로드 완료!",
            },
            {
                "sender": "배달의민족",
                "app_name": "배달의민족",
                "raw_text": "주문하신 음식이 10분 후 도착 예정입니다. 배달원 정보: 김기사님",
                "masked_text": "주문하신 음식이 10분 후 도착 예정입니다. 배달원 정보: 김*사님",
            },
        ]

        print("Creating alarm notification fixtures...")
        for alarm_data in test_alarms:
            db.add(
                IncomingAlarm(
                    raw_text=alarm_data["raw_text"],
                    masked_text=alarm_data["masked_text"],
                    sender=alarm_data["sender"],
                    app_name=alarm_data["app_name"],
                    status="pending",
                    received_at=utcnow(),
                )
            )
            print(f"Added {alarm_data['app_name']} / {alarm_data['sender']}")

        db.commit()
        print(f"Created {len(test_alarms)} fixture alarms.")
    finally:
        db.close()


if __name__ == "__main__":
    create_test_alarms()
