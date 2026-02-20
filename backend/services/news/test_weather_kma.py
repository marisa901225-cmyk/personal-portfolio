import asyncio
import logging
import sys
import os
from datetime import datetime, timedelta, timezone

# 프로젝트 루트를 PYTHONPATH에 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

# 로깅 설정
logging.basicConfig(level=logging.INFO)

async def test_weather():
    from backend.services.news.weather import fetch_weather_forecast
    from backend.core.config import settings
    
    print(f"KMA_SERVICE_KEY: {settings.kma_service_key[:5]}..." if settings.kma_service_key else "KMA_SERVICE_KEY: None")
    
    print("\n[테스트 시작] 기상청 단기예보 & 초단기실황 API 호출")
    msg = await fetch_weather_forecast()
    
    print("-" * 50)
    if msg:
        print(msg)
    else:
        print("날씨 정보를 가져오는 데 실패했어. (API 키나 네트워크 확인 필요)")
    print("-" * 50)

if __name__ == "__main__":
    asyncio.run(test_weather())
