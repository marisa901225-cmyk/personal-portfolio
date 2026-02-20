import asyncio
import pytest
from backend.services.news.weather import fetch_weather_forecast

@pytest.mark.asyncio
async def test_fetch_weather_forecast():
    """날씨 정보 수신 테스트 (실제 API 호출)"""
    print("\n--- [날씨 서비스 실시간 수신 테스트] ---")
    message = await fetch_weather_forecast()
    
    assert message is not None, "날씨 정보를 가져오는데 실패했습니다. API 키를 확인해주세요."
    assert isinstance(message, str), "수신된 메시지는 문자열이어야 합니다."
    assert len(message) > 0, "수신된 메시지가 비어 있습니다."
    
    print("\n[수신된 메시지 샘플]")
    print("-" * 50)
    print(message[:200] + "..." if len(message) > 200 else message)
    print("-" * 50)

if __name__ == "__main__":
    # 직접 실행 시에도 작동하도록 asyncio.run 사용
    message = asyncio.run(fetch_weather_forecast())
    print(message)
