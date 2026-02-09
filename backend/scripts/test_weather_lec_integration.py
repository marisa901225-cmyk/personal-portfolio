import asyncio
import logging
import sys
import os

# 프로젝트 루트를 경로에 추가
sys.path.append('/app')

from backend.services.news.weather import fetch_weather_forecast
from backend.services.news.weather_cache import clear_old_caches

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_weather_briefing_with_lec():
    logger.info("LEC 결과가 포함된 날씨 브리핑 통합 테스트 시작...")
    
    # 기존 캐시 삭제 (프레시한 테스트를 위해)
    clear_old_caches()
    
    try:
        # 날씨 브리핑 생성 실행 (내부적으로 LEC 결과 수집 포함됨)
        message = await fetch_weather_forecast()
        
        print("\n" + "="*50)
        print("Generated Weather Briefing with LEC Results:")
        print("="*50)
        if message:
            print(message)
        else:
            print("❌ 메시지 생성 실패")
        print("="*50 + "\n")
        
    except Exception as e:
        logger.error(f"통합 테스트 중 오류 발생: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_weather_briefing_with_lec())
