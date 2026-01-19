import asyncio
import os
import sys
from sqlalchemy.orm import Session
from datetime import datetime, timezone

# 프로젝트 루트를 path에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from backend.core.database import SessionLocal
from backend.services.alarm.match_notifier import check_upcoming_matches
from backend.services.alarm.llm_logic import generate_daily_catchphrases

async def verify():
    db = SessionLocal()
    try:
        print("1. 캐치프레이즈 재생성 시도...")
        success = await generate_daily_catchphrases()
        print(f"   결과: {'성공' if success else '실패'}")
        
        with open("backend/data/esports_catchphrases_v2.json", "r", encoding="utf-8") as f:
            import json
            data = json.load(f)
            print(f"   LoL 템플릿 예시: {data.get('LoL', [])[:1]}")
            print(f"   Valorant 템플릿 예시: {data.get('Valorant', [])[:1]}")

        print("\n2. 시간대 변환 로직 확인을 위한 가상 경기 알림 테스트...")
        # 이 부분은 match_notifier.py 수정 후 실제 알림이 KST로 나가는지 로그로 확인해야 함
        # 현재는 check_upcoming_matches가 실제 텔레그램을 보내므로 주의
        
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(verify())
