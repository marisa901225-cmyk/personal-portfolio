#!/usr/bin/env python3
"""
테스트용 알람 생성 스크립트
실제 알람처럼 DB에 저장하여 알람 요약 기능을 테스트합니다.
"""
import sys
import os

# 경로 설정
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.db import SessionLocal
from core.models import IncomingAlarm
from core.time_utils import utcnow

def create_test_alarms():
    """테스트용 알람들을 생성"""
    db = SessionLocal()
    
    test_alarms = [
        {
            "sender": "홍길동",
            "app_name": "카카오톡",
            "raw_text": "내일 2시에 강남역에서 만날까? 점심 먹으면서 프로젝트 이야기하자!",
            "masked_text": "내일 2시에 강남역에서 만날까? 점심 먹으면서 프로젝트 이야기하자!"
        },
        {
            "sender": "김철수",
            "app_name": "카카오톡", 
            "raw_text": "회의 자료 확인 부탁드립니다. 내일까지 피드백 주세요~",
            "masked_text": "회의 자료 확인 부탁드립니다. 내일까지 피드백 주세요~"
        },
        {
            "sender": "리꼬타",
            "app_name": "문피아",
            "raw_text": "군필 미소녀가 방송을 너무 잘함 - 125화 업로드 완료!",
            "masked_text": "군필 미소녀가 방송을 너무 잘함 - 125화 업로드 완료!"
        },
        {
            "sender": "배달의민족",
            "app_name": "배달의민족",
            "raw_text": "주문하신 음식이 10분 후 도착 예정입니다. 배달원 정보: 김기사님",
            "masked_text": "주문하신 음식이 10분 후 도착 예정입니다. 배달원 정보: 김*사님"
        }
    ]
    
    print("🧪 테스트 알람 생성 중...")
    
    for alarm_data in test_alarms:
        alarm = IncomingAlarm(
            raw_text=alarm_data["raw_text"],
            masked_text=alarm_data["masked_text"],
            sender=alarm_data["sender"],
            app_name=alarm_data["app_name"],
            status="pending",
            received_at=utcnow()
        )
        db.add(alarm)
        print(f"✅ {alarm_data['app_name']} - {alarm_data['sender']}: {alarm_data['raw_text'][:30]}...")
    
    db.commit()
    print(f"\n✨ 총 {len(test_alarms)}개의 테스트 알람이 생성되었습니다!")
    print("📱 다음 알람 처리 사이클(매 5분)에 요약이 텔레그램으로 전송됩니다.\n")
    
    db.close()

if __name__ == "__main__":
    create_test_alarms()
