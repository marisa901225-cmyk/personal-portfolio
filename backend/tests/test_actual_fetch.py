import sys
import os
import asyncio
from zoneinfo import ZoneInfo

# 프로젝트 경로 추가
sys.path.append(os.getcwd())

from backend.services.news.weather_kma import fetch_ultra_short_snapshot
from backend.core.config import settings

async def test_actual_fetch_1530():
    KST = ZoneInfo("Asia/Seoul")
    service_key = settings.kma_service_key
    
    if not service_key:
        print("❌ KMA_SERVICE_KEY not set in .env")
        return

    print("📡 Fetching actual ultra-short forecast data (including 15:30 slot)...")
    # nx, ny는 서울 기준 (60, 127)
    data = await fetch_ultra_short_snapshot(service_key, nx=60, ny=127)
    
    if data:
        print("✅ Data fetched successfully!")
        print(f"📊 Weather Data: {data}")
        print(f"🕒 Base Time used: {data.get('fcst_date')} {data.get('fcst_time')}")
    else:
        print("❌ Failed to fetch data. Check API Key or Network.")

if __name__ == "__main__":
    asyncio.run(test_actual_fetch_1530())
