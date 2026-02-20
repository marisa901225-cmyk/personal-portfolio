import asyncio
import os
import sys
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.integrations.kis.kis_client import get_futures_daily_chart

KST = ZoneInfo("Asia/Seoul")

async def test_fields():
    print("🔍 KIS 선물 일봉 데이터 필드 조사 중...")
    
    now = datetime.now(KST)
    end_date = now.strftime("%Y%m%d")
    # 넉넉하게 60일치 요청
    start_date = (now - timedelta(days=60)).strftime("%Y%m%d")
    
    symbol = "101000"
    data = await get_futures_daily_chart(symbol, start_date, end_date)
    
    if not data or not data.get("output2"):
        print("❌ 데이터를 가져오지 못했습니다.")
        return

    history = data.get("output2")
    print(f"✅ 데이터 수신 성공! (총 {len(history)}거래일)")
    
    # 첫 번째 레코드(오늘) 필드 전부 출력
    print("\n[최신 거래일 필드 샘플]")
    sample = history[0]
    for key, val in sample.items():
        print(f" - {key}: {val}")

    # OI 추정 필드: stnd_prng_cls_code, acml_trpb 등 확인 필요
    # 보통 일봉에서는 미결제약정이 hts_otst_stpl_qty 등으로 오거나 
    # TR 명세에 따라 다름. 'stnd_prng_cls_code'는 보통 기준가격.

if __name__ == "__main__":
    asyncio.run(test_fields())
