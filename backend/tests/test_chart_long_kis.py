import asyncio
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.integrations.kis.kis_client import get_futures_daily_chart

KST = ZoneInfo("Asia/Seoul")

async def test():
    now = datetime.now(KST)
    # 60일 전부터 오늘까지 요청
    start = (now - timedelta(days=60)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    
    print(f"🔍 차트 API 기반 과거 데이터 조회 시작 ({start} ~ {end})...")
    d = await get_futures_daily_chart('101000', start, end)
    
    if d:
        history = d.get("output2", [])
        print(f"✅ Data Count: {len(history)}")
        if history:
            print(f"🔹 최신 데이터: {history[0].get('stck_bsop_date')} / {history[0].get('futs_prpr')}")
            if len(history) > 1:
                print(f"🔹 가장 오래된 데이터: {history[-1].get('stck_bsop_date')} / {history[-1].get('futs_prpr')}")
    else:
        print("❌ API 응답이 없거나 실패했습니다.")

if __name__ == "__main__":
    asyncio.run(test())
