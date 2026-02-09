import asyncio
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.integrations.kis.kis_client import get_futures_period_price

KST = ZoneInfo("Asia/Seoul")

async def test():
    now = datetime.now(KST)
    start = (now - timedelta(days=60)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    
    print(f"🔍 기간별 시세 조회 시작 ({start} ~ {end})...")
    d = await get_futures_period_price('101000', start, end)
    
    if d:
        history = d.get("output2", [])
        print(f"✅ Data Count: {len(history)}")
        if history:
            print(f"🔹 최신 데이터 샘플: {history[0]}")
            if len(history) > 1:
                print(f"🔹 이전 데이터 샘플: {history[-1]}")
    else:
        print("❌ API 응답이 없거나 실패했습니다.")

if __name__ == "__main__":
    asyncio.run(test())
