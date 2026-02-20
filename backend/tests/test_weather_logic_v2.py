import asyncio
import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from backend.services.news.weather_cache import WeatherData, save_weather_cache, load_weather_cache, CACHE_DIR
from backend.services.news.weather import prefetch_weather_at_05, fetch_weather_from_cache

KST = ZoneInfo("Asia/Seoul")

async def test_weather_logic_improvement():
    print("=== Testing Weather Logic Improvement (05:00 vs 06:00) ===")
    
    # 1. 테스트 환경 정비 (캐시 디렉토리 청소)
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now(KST).strftime("%Y%m%d")
    
    # 2. 05:00 데이터 저장 시뮬레이션
    print("\n1. Simulating 05:00 forecast collection...")
    weather_05 = WeatherData(
        message="",
        temp="-10",
        weather_status="추운 맑음",
        pop="0",
        base_date=today,
        base_time="0500",
        cached_at=datetime.now(KST).isoformat()
    )
    save_weather_cache(weather_05)
    
    loaded = load_weather_cache()
    print(f"Loaded cache base_time: {loaded.base_time} (Expected: 0500)")
    
    # 3. 06:00 데이터 수집 시뮬레이션 (동일 조건에서 fetch_from_api가 0600을 반환한다고 가정)
    # 실제 API 호출 대신 save_weather_cache를 직접 호출하여 로직 확인
    print("\n2. Simulating 06:00 forecast update...")
    weather_06 = WeatherData(
        message="",
        temp="-9",
        weather_status="조금 덜 추운 맑음",
        pop="0",
        base_date=today,
        base_time="0600",
        cached_at=datetime.now(KST).isoformat()
    )
    
    # 여기서 weather.py의 prefetch_weather_at_05 logic check
    # 이미 0500이 있지만 0600이 더 최신이므로 저장되어야 함
    save_weather_cache(weather_06)
    
    # 4. 최신 캐시 로드 확인
    print("\n3. Loading latest cache...")
    latest = load_weather_cache()
    print(f"Latest loaded cache base_time: {latest.base_time} (Expected: 0600)")
    
    if latest.base_time == "0600":
        print("[SUCCESS] Cache logic correctly prioritizes 06:00 over 05:00!")
    else:
        print("[FAILURE] Cache logic failed to prioritize 06:00.")

    # 5. 브리핑 메시지 생성 시 시각 확인
    print("\n4. Generating briefing message from cache...")
    msg = await fetch_weather_from_cache()
    # 로그에 "Using cached weather data from 0600" 이 찍혀야 함 (외부 로그 확인 필요)
    print(f"Generated message snippet: {msg[:100]}...")
    
    if "오전 7시" in msg:
         print("[SUCCESS] Display time correctly set to 7 AM (Briefing Time)!")

if __name__ == "__main__":
    asyncio.run(test_weather_logic_improvement())
