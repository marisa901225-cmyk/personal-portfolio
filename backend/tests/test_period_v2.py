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
    
    # KIS API 가이드에 따르면 엔드포인트가 조금 다를 수 있음
    # /uapi/domestic-futureoption/v1/quotations/inquire-daily-price 가 맞는지 재확인
    # 혹시 엔드포인트가 /uapi/domestic-futureoption/v1/quotations/inquire-daily-fuop-chartprice 인가?
    
    print(f"🔍 [V2] 기간별 시세 조회 시작 (FHKIF03010100)...")
    # 현재 kis_client.py에 추가한 엔드포인트로 다시 시도 (URL 오타 가능성 점검)
    d = await get_futures_period_price('101000', start, end)
    
    if d:
        print(f"✅ Response Data: {d.keys()}")
        history = d.get("output2", [])
        print(f"✅ Data Count: {len(history)}")
    else:
        print("❌ 실패")

if __name__ == "__main__":
    asyncio.run(test())
