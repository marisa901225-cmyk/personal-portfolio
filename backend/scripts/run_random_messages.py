import asyncio
import os
import sys
import logging
from datetime import datetime

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.alarm.llm_logic import summarize_with_llm
from backend.services.llm import LLMService
from integrations.telegram import send_telegram_message

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_random_messages")

async def test_random_messages():
    logger.info("Starting random message robust test...")
    
    # 10분 체크 우회를 위해 상태 파일 조작
    from backend.services.alarm.llm_logic import _RANDOM_TOPIC_STATE_FILE
    import json
    from datetime import datetime, timedelta
    
    os.makedirs(os.path.dirname(_RANDOM_TOPIC_STATE_FILE), exist_ok=True)
    with open(_RANDOM_TOPIC_STATE_FILE, "w", encoding="utf-8") as f:
        # 20분 전으로 설정하여 catch-up 로직 발동 유도
        past = (datetime.now() - timedelta(minutes=20)).isoformat(timespec="seconds")
        json.dump({"last_sent_at": past}, f)
    
    from backend.services.alarm.llm_logic import summarize_with_llm
    from backend.services.alarm.llm_refiner import dump_llm_draft
    
    try:
        logger.info("Calling summarize_with_llm([]) with catch-up logic...")
        # summarize_with_llm([]) 내부에서 dump_llm_draft가 호출됨
        result = await summarize_with_llm([])
        
        if result:
            logger.info(f"Generated Message: {result[:50]}...")
            await send_telegram_message(f"<b>[랜덤 통합 테스트]</b>\n\n{result}")
            logger.info("Test message sent successfully!")
        else:
            logger.warning("summarize_with_llm returned None. Check 10-min logic or LLM errors.")
            
    except Exception as e:
        logger.error(f"Test failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(test_random_messages())


if __name__ == "__main__":
    asyncio.run(test_random_messages())
