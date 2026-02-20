import asyncio
import logging
import os
from unittest.mock import AsyncMock, patch
import json
import os
import sys

# (실제 API 호출을 하려면 이 부분을 주석 해제하거나 환경 변수를 설정해야 함)
# os.environ["OPEN_API_KEY"] = "test-key"

async def test_briefing_logic():
    from backend.services.scheduler.core import job_morning_briefing
    from backend.services.alarm.processor import process_pending_alarms
    from backend.core.config import settings

    print("--- Settings Check ---")
    print(f"OPEN_API_KEY present: {bool(settings.open_api_key)}")
    
    # 텔레그램 전송 Mock
    with patch("backend.integrations.telegram.send_telegram_message", new_callable=AsyncMock) as mock_send:
        # 날씨 프리페치 캐시 Mock
        with patch("backend.services.news.weather.fetch_weather_from_cache", new_callable=AsyncMock) as mock_weather:
            mock_weather.return_value = "오늘의 날씨는 맑음입니다."
            
            # 알람 처리 Mock (실제 호출 대신 인자 확인)
            with patch("backend.services.alarm.processor.summarize_with_llm", new_callable=AsyncMock) as mock_summary:
                mock_summary.return_value = "요약된 알람 내용입니다."
                
                print("\n--- Running Morning Briefing Job ---")
                await job_morning_briefing()
                
                # 검증
                print("\n--- Verification Results ---")
                print(f"Telegram sent: {mock_send.call_count} times")
                
                # 7시 알람 요약 호출 시 인자 확인
                # job_morning_briefing -> process_pending_alarms -> summarize_with_llm
                # summarize_with_llm.call_args_list에서 model 인자 확인
                print(f"LLM Summary called: {mock_summary.call_count} times")
                if mock_summary.call_count > 0:
                    args, kwargs = mock_summary.call_args
                    print(f"Model used: {kwargs.get('model')}")
                    print(f"API Key used: {bool(kwargs.get('api_key'))}")
                    print(f"Base URL used: {kwargs.get('base_url')}")
                    
                    if kwargs.get('model') == "openai/gpt-5.1-chat":
                        print("✅ Success: Correct model passed to summary logic!")
                    else:
                        print("❌ Failure: Incorrect model passed.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_briefing_logic())
