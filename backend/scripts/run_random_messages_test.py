import asyncio
import os
import sys
import logging
from datetime import datetime

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.alarm.llm_logic import summarize_with_llm
from backend.services.llm import LLMService
from backend.integrations.telegram import send_telegram_message

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_random_messages")

async def test_random_messages():
    logger.info("Starting random message instant test...")
    
    # LLM 서비스 로드 확인
    llm_service = LLMService.get_instance()
    # 모델 로드 상태 강제 확인
    if not llm_service.is_loaded():
        logger.info("LLM model is not loaded in this process. Attempting to check initialization...")

    from backend.services.alarm.llm_logic import (
        _load_recent_categories, 
        _pick_keywords_for_constraints,
        _save_recent_category,
        _save_last_random_topic_sent_at,
        load_prompt,
        generate_with_main_llm_async,
        clean_exaone_tokens,
        clean_meta_headers
    )
    import random
    
    categories = ["우주/천문학", "물리학/화학", "생물학/자연", "역사/문화", "기술/엔지니어링", "수학/논리", "심리학/뇌과학", "게임/e스포츠", "영화/드라마/음악", "언어유희/드립", "음식/요리", "지리/여행"]
    formats = ["질문형으로 시작해라", "팩트 단언형으로 시작해라", "감탄형으로 시작해라", "수수께끼/퀴즈형으로 시작해라", "뉴스속보형으로 시작해라", "TMI형으로 시작해라"]
    
    recent = _load_recent_categories()
    available_categories = [c for c in categories if c not in recent]
    if not available_categories: available_categories = categories
    forced_category = random.choice(available_categories)
    forced_format = random.choice(formats)
    
    logger.info(f"Selected Category: {forced_category}, Format: {forced_format}")
    
    must_keywords = _pick_keywords_for_constraints(forced_category, count=4)
    prompt_content = load_prompt(
        "random_topic",
        category=forced_category,
        format=forced_format,
        must_keywords=", ".join(must_keywords),
        avoid_keywords="해당 없음"
    )
    
    messages = [{"role": "user", "content": prompt_content}]
    
    try:
        logger.info("Generating with LLM...")
        result = await generate_with_main_llm_async(messages, max_tokens=512, temperature=0.7)
        if not result:
            logger.error("LLM generated empty result")
            return
            
        result = clean_exaone_tokens(result)
        final_result = clean_meta_headers(result)
        
        if final_result:
            logger.info(f"Generated Message: {final_result[:50]}...")
            await send_telegram_message(f"<b>[랜덤 즉시 테스트]</b>\n\n{final_result}")
            _save_recent_category(forced_category)
            _save_last_random_topic_sent_at(datetime.now())
            logger.info("Test message sent successfully!")
    except Exception as e:
        logger.error(f"Test failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(test_random_messages())


if __name__ == "__main__":
    asyncio.run(test_random_messages())
