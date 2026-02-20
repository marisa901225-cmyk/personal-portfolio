import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from backend.services.news.weather import _generate_weather_message

# 로깅 설정 (필요 시)
# logging.basicConfig(level=logging.INFO)

async def test_weather_briefing_time():
    KST = ZoneInfo("Asia/Seoul")
    
    # 가상의 날씨 데이터
    temp = "-10"
    weather_status = "맑음 ☀️"
    base_date = "20260209"
    base_time = "0500" # 예보 기준 시간
    
    # 1. display_datetime 없이 생성 (기존 방식 - 예보 시간 노출)
    print("--- Testing with display_datetime=None (Forecast Time) ---")
    msg_forecast = await _generate_weather_message(
        temp=temp,
        weather_status=weather_status,
        base_date=base_date,
        base_time=base_time,
        include_briefing_context=False,
        display_datetime=None
    )
    # result-mocking: generate_weather_message_with_llm 내부에서 format_datetime_korean 호출 시 
    # base_date/base_time을 사용함
    print(f"Generated Message Preview (starts with): \n{msg_forecast[:100]}...")
    
    # 2. display_datetime 포함하여 생성 (수정 방식 - 현재 시간 노출)
    print("\n--- Testing with display_datetime=now (Briefing Time) ---")
    now = datetime.now(KST).replace(hour=7, minute=0) # 7시로 가정
    msg_now = await _generate_weather_message(
        temp=temp,
        weather_status=weather_status,
        base_date=base_date,
        base_time=base_time,
        include_briefing_context=False,
        display_datetime=now
    )
    print(f"Generated Message Preview (starts with): \n{msg_now[:100]}...")
    
    # "2026년 2월 9일 오전 7시"가 포함되어야 함
    if "7시" in msg_now:
        print("\n[SUCCESS] Briefing time (7 AM) detected in message!")
    else:
        print("\n[WARNING] Briefing time (7 AM) not explicitly found. Check LLM output content.")

if __name__ == "__main__":
    asyncio.run(test_weather_briefing_time())
