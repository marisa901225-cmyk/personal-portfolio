import asyncio
import logging
import sys
import os

# 프로젝트 루트를 경로에 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from backend.services.alarm_service import AlarmService
from backend.core.db import SessionLocal

async def smoke_test():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("smoke_test")
    
    logger.info("Starting OpenAI Flex Service Tier Smoke Test...")
    logger.info(f"Using AI_REPORT_MODEL: {os.getenv('AI_REPORT_MODEL', 'gpt-5-mini')}")
    logger.info(f"Using AI_REPORT_TIMEOUT: {os.getenv('AI_REPORT_TIMEOUT_SEC', '900')}s")
    
    try:
        # 테스트용 임시 파일 경로 설정
        test_save_path = os.path.join(os.path.dirname(__file__), "test_catchphrases.json")
        os.environ["CATCHPHRASE_SAVE_PATH"] = test_save_path
        
        # e스포츠 캐치프레이즈 생성
        logger.info(f"Calling generate_daily_catchphrases (saving to {test_save_path})...")
        result = await AlarmService.generate_daily_catchphrases()
        
        if result:
            logger.info("✅ SUCCESS: Catchphrases generated successfully.")
            # 생성된 파일 확인
            if os.path.exists(test_save_path):
                import json
                with open(test_save_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"Generated Data Preview (LoL): {data.get('LoL', [])[:2]}")
                # 테스트 완료 후 파일 삭제
                os.remove(test_save_path)
                logger.info(f"Cleanup: Removed temporary test file {test_save_path}")
            else:
                logger.warning("Catchphrase file not found even though function returned True.")
        else:
            logger.error("❌ FAILURE: Function returned False. Check logs for API errors.")
            
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR during smoke test: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(smoke_test())
