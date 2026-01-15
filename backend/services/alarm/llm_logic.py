# backend/services/alarm/llm_logic.py
# 420줄 alarm_service.py에서 추출한 LLM 로직
import logging
from datetime import datetime
from typing import List, Optional

from .sanitizer import infer_source, sanitize_llm_output, clean_exaone_tokens
from ..prompt_loader import load_prompt
from ..llm_service import LLMService

logger = logging.getLogger(__name__)


async def summarize_with_llm(items: List[dict]) -> str:
    """
    3단계: Local LLM (llama-cpp-python)을 사용하여 여러 알림을 요약한다.
    items: [{"text": "...", "sender": "..."}, ...]
    알람이 없을 때는 LLM이 랜덤으로 재미있는 말을 한다.
    """
    llm_service = LLMService.get_instance()
    
    if not llm_service.is_loaded():
        if not items:
            return "🤖 LLM 모델이 로드되지 않았습니다... 알람도 없고, 모델도 없네요 😅"
        return "\n".join([f"- [{item['sender']}] {item['text']}" for item in items])
    
    # 알람이 없을 때: 재미있는 말 하기 모드 (10분 간격으로만)
    if not items:
        current_minute = datetime.now().minute
        # 10분 간격이 아니면 조용히 스킵 (:00, :10, :20, :30, :40, :50만 전송)
        if current_minute % 10 != 0:
            logger.info(f"No alarms, but skipping random message (minute={current_minute}, not 10-min interval)")
            return None  # 메시지 안 보냄
        
        # 매 시간 정각(:00)에 LLM 세션 리셋 (주제 집착 방지)
        if current_minute == 0:
            llm_service.reset_context()
            logger.info("Hourly LLM context reset performed.")
        
        # 현재 시간의 분(minute)을 기반으로 카테고리 & 형식 강제 선택 (다양성 확보)
        category_index = (current_minute // 10) % 5  # 0~4 범위
        format_index = (datetime.now().hour + category_index) % 5  # 시간 + 카테고리로 형식도 분산
        
        categories = [
            "지식/과학 (우주, 물리학, 생물학, 기술사, 수학 퍼즐)",
            "역사/문화 (고대문명, 이상한 역사, 폐기된 발명품, 기묘한 법률)",
            "엔터/취미 (게임 트리비아, e스포츠, 마이너 스포츠, 영화/드라마 비하인드)",
            "언어유희/드립 (말장난, 아재개그, 논리 역설, 수수께끼)",
            "철학/심리 (사고실험, 심리학 실험, 인지 편향, 재미있는 통계)"
        ]
        
        # 문장 시작 형식도 강제 (반복 방지)
        formats = [
            "질문형으로 시작해라 (예: '혹시 알아?' / '이거 들어봤어?')",
            "팩트 단언형으로 시작해라 (예: '사실...' / '진짜 신기한 건...')",
            "감탄형으로 시작해라 (예: '와!' / '헐!' / '대박!')",
            "수수께끼/퀴즈형으로 시작해라 (예: 'OO는 왜 OO일까?')",
            "선택형으로 시작해라 (예: 'A vs B 중 뭐가 나을까?')"
        ]
        
        forced_category = categories[category_index]
        forced_format = formats[format_index]
        
        # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
        prompt_content = load_prompt("random_topic", category=forced_category, format=forced_format)
        if not prompt_content:
            # 폴백: 파일이 없으면 기본 메시지
            return "🤔 오늘도 심심한 하루... 뭐 재미있는 거 없나?"
        
        messages = [
            {
                "role": "user",
                "content": prompt_content
            }
        ]
        
        logger.info("No alarms to process. Asking LLM for random wisdom...")
        result = llm_service.generate_chat(
            messages, 
            max_tokens=128, 
            temperature=0.8,
            stop=["Okay", "let me", "Let me", "I'll", "아하", "음,", "사용자가", "지시사항을"]
        )
        result = clean_exaone_tokens(result)
        logger.info(f"LLM Random Response: {result}")
        
        # 결과 검증 (영어가 너무 많거나 비어있으면 skip)
        if not result or len(result.strip()) < 10:
            logger.warning("Generated message too short, skipping.")
            return None
            
        import re
        korean_chars = len(re.findall(r'[가-힣]', result))
        if korean_chars / len(result) < 0.3:
            logger.warning(f"Low Korean ratio ({korean_chars/len(result):.2f}), skipping.")
            return None
            
        return result

    
    # 알림 목록 구성 (발신자 포함)
    notification_list = []
    for item in items:
        source = infer_source(item)
        title = item.get('app_title') or ""
        conv = item.get('conversation') or ""
        text = item.get('text') or ""
        
        # Tasker 변수가 치환 안 된 경우 제외
        if title.startswith('%'): title = ""
        if conv.startswith('%'): conv = ""
        
        context = f"[앱: {source}]"
        if title: context += f" 제목: {title}"
        if conv: context += f" 발신/대화: {conv}"
        
        notification_list.append(f"- {context} 본문: {text}")

    # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
    notifications_str = "\n".join(notification_list)
    prompt_content = load_prompt("alarm_summary", notifications=notifications_str)
    
    if not prompt_content:
        # 폴백: 파일이 없으면 기본 포맷 사용
        prompt_content = f"아래 스마트폰 알림들을 한국어로 요약해줘:\n{notifications_str}"
    
    messages = [
        {
            "role": "user",
            "content": prompt_content
        }
    ]
    
    logger.info(f"LLM Chat Messages: {messages}")
    total_prompt_len = sum(len(m['content']) for m in messages)
    logger.info(f"LLM Prompt total length: {total_prompt_len} characters")
    result = llm_service.generate_chat(messages, max_tokens=512)
    logger.info(f"LLM Response: {result}")
    
    # 환각 제거 및 특수 토큰 제거 후 반환
    result = sanitize_llm_output(items, result)
    result = clean_exaone_tokens(result)
    return result


async def summarize_expenses_with_llm(expenses: List[dict]) -> str:
    """
    가계부 내역(결제 승인)을 분석하여 짧은 코멘트를 생성한다.
    """
    if not expenses:
        return ""
    
    llm_service = LLMService.get_instance()
    
    if not llm_service.is_loaded():
        return ""

    expense_list = []
    for e in expenses:
        expense_list.append(f"- {e['merchant']}: {abs(e['amount']):,.0f}원 ({e['category']})")

    messages = [
        {"role": "user", "content": f"""You are a financial assistant. Analyze the following payment records and provide a short, witty one-sentence analysis in Korean about the user's spending patterns or characteristics.
Start directly with the result without any introductory phrases or greetings.

[Payments]
{chr(10).join(expense_list)}"""}
    ]
    result = llm_service.generate_chat(messages, max_tokens=128)
    return clean_exaone_tokens(result)
