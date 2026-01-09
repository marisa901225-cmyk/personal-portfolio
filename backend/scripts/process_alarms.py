import asyncio
import logging
import os
import sys
from pathlib import Path

# 프로젝트 루트를 패스에 추가
sys.path.append(os.getcwd())

from backend.core.db import SessionLocal
from backend.services.alarm_service import AlarmService
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("process_alarms")

async def main():
    logger.info("Starting alarm batch processing...")
    
    db = SessionLocal()
    try:
        # AlarmService를 통해 대기 중인 알림 처리
        # (Tier 1: Rule, Tier 2: NB, Tier 3: Summary 준비 포함)
        await AlarmService.process_pending_alarms(db)
        logger.info("Batch processing completed successfully.")
    except Exception as e:
        logger.error(f"Error during batch processing: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
