# backend/services/alarm/llm_logic.py
# 420줄 alarm_service.py에서 추출한 LLM 로직
import logging
import os
import random
import re
from datetime import datetime
from datetime import timedelta
from typing import List, Optional

import asyncio
import httpx
from .sanitizer import infer_source, sanitize_llm_output, clean_exaone_tokens
from ..prompt_loader import load_prompt
from ..llm_service import LLMService
from .llm_refiner import (
    STOP_TOKENS,
    generate_with_main_llm_async,
    refine_draft_with_light_llm_async,
    dump_llm_draft,
    clean_meta_headers
)

logger = logging.getLogger(__name__)

# 랜덤 메시지 카테고리 중복 방지용 (최근 N개 선택 카테고리)
_recent_categories: List[str] = []
_RECENT_CATEGORY_MAX = 3  # 최근 3개까지 중복 방지
_RECENT_CATEGORY_FILE = os.path.join(os.path.dirname(__file__), "../../data/recent_categories.json")
_RANDOM_TOPIC_STATE_FILE = os.path.join(os.path.dirname(__file__), "../../data/random_topic_state.json")

_SPACE_KEYWORDS = (
    "우주",
    "천문",
    "행성",
    "은하",
    "블랙홀",
    "빅뱅",
    "성운",
    "외계",
    "항성",
    "혜성",
    "소행성",
)

_CATEGORY_KEYWORDS = {
    "우주/천문학": (
        "우주",
        "천문",
        "행성",
        "별",
        "은하",
        "블랙홀",
        "성운",
        "궤도",
        "망원경",
    ),
    "물리학/화학": (
        "물리",
        "화학",
        "원자",
        "분자",
        "원소",
        "반응",
        "에너지",
        "전자",
        "양자",
        "촉매",
    ),
    "생물학/자연": (
        "생물",
        "세포",
        "진화",
        "유전자",
        "생태",
        "동물",
        "식물",
        "미생물",
        "자연",
        "종",
    ),
    "역사/문화": (
        "역사",
        "왕",
        "제국",
        "전쟁",
        "유적",
        "전통",
        "문화",
        "고대",
        "중세",
        "문명",
    ),
    "기술/엔지니어링": (
        "기술",
        "엔지니어",
        "설계",
        "기계",
        "로봇",
        "회로",
        "알고리즘",
        "발명",
        "시스템",
        "자동화",
    ),
    "수학/논리": (
        "수학",
        "정리",
        "증명",
        "논리",
        "확률",
        "함수",
        "기하",
        "대수",
        "퍼즐",
        "추론",
    ),
    "심리학/뇌과학": (
        "심리",
        "뇌",
        "인지",
        "기억",
        "감정",
        "실험",
        "편향",
        "의식",
        "신경",
        "행동",
    ),
    "게임/e스포츠": (
        "e스포츠",
        "프로게이머",
        "리그 오브 레전드",
        "롤",
        "발로란트",
        "lck",
        "msi",
        "월즈",
        "챔피언스",
        "픽밴",
        "메타",
        "랭크",
    ),
    "영화/드라마/음악": (
        "영화",
        "드라마",
        "음악",
        "감독",
        "배우",
        "ost",
        "사운드트랙",
        "앨범",
        "촬영",
        "무대",
    ),
    "언어유희/드립": (
        "말장난",
        "언어유희",
        "드립",
        "중의",
        "라임",
        "언어",
        "어휘",
        "말맛",
        "말끝",
        "말꼬리",
    ),
    "음식/요리": (
        "요리",
        "음식",
        "재료",
        "맛",
        "향",
        "조리",
        "양념",
        "레시피",
        "식감",
        "불맛",
    ),
    "지리/여행": (
        "지리",
        "여행",
        "지도",
        "대륙",
        "국가",
        "도시",
        "산맥",
        "강",
        "섬",
        "기후",
    ),
}


def _load_recent_categories() -> List[str]:
    """영구 저장된 최근 카테고리 목록 로드"""
    global _recent_categories
    if _recent_categories:
        return _recent_categories
    try:
        if os.path.exists(_RECENT_CATEGORY_FILE):
            import json
            with open(_RECENT_CATEGORY_FILE, "r", encoding="utf-8") as f:
                _recent_categories = json.load(f)
    except Exception:
        pass
    return _recent_categories


def _load_last_random_topic_sent_at() -> Optional[datetime]:
    try:
        if not os.path.exists(_RANDOM_TOPIC_STATE_FILE):
            return None
        import json
        with open(_RANDOM_TOPIC_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        val = (data or {}).get("last_sent_at")
        if not val:
            return None
        return datetime.fromisoformat(val)
    except Exception:
        return None


def _save_last_random_topic_sent_at(sent_at: datetime) -> None:
    try:
        import json
        os.makedirs(os.path.dirname(_RANDOM_TOPIC_STATE_FILE), exist_ok=True)
        with open(_RANDOM_TOPIC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_sent_at": sent_at.isoformat(timespec="seconds")}, f, ensure_ascii=False)
    except Exception:
        pass


def _save_recent_category(category: str):
    """카테고리를 최근 목록에 추가하고 파일에 저장"""
    global _recent_categories
    _load_recent_categories()
    if category in _recent_categories:
        _recent_categories.remove(category)
    _recent_categories.insert(0, category)
    _recent_categories = _recent_categories[:_RECENT_CATEGORY_MAX]
    try:
        import json
        os.makedirs(os.path.dirname(_RECENT_CATEGORY_FILE), exist_ok=True)
        with open(_RECENT_CATEGORY_FILE, "w", encoding="utf-8") as f:
            json.dump(_recent_categories, f, ensure_ascii=False)
    except Exception:
        pass

def _get_korean_ratio(text: str) -> float:
    """텍스트의 한국어 비율을 계산한다."""
    if not text:
        return 0
    import re
    korean_chars = len(re.findall(r'[가-힣]', text))
    meaningful_chars = len(re.findall(r'[가-힣a-zA-Z0-9]', text))
    if meaningful_chars == 0:
        return 0
    return korean_chars / meaningful_chars

def _is_space_drift(text: str, category: str) -> bool:
    """우주/천문학 카테고리가 아닐 때 우주 관련 키워드가 튀는지 검사한다."""
    if not text:
        return False
    if "우주" in category or "천문" in category:
        return False
    return any(keyword in text for keyword in _SPACE_KEYWORDS)

def _has_category_anchor(text: str, category: str) -> bool:
    """카테고리별 핵심 키워드가 최소 1개 포함되는지 검사한다."""
    if not text:
        return False
    keywords = _CATEGORY_KEYWORDS.get(category)
    if not keywords:
        return True
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _pick_keywords_for_constraints(category: str, *, count: int = 4) -> list[str]:
    keywords = list(_CATEGORY_KEYWORDS.get(category) or [])
    if not keywords:
        return []
    korean_keywords = [k for k in keywords if re.search(r"[가-힣]", k)]
    pool = korean_keywords or keywords
    if len(pool) <= count:
        return pool
    return random.sample(pool, k=count)


def _build_random_topic_fallback(category: str) -> str:
    keywords = list(_CATEGORY_KEYWORDS.get(category) or [])
    korean_keywords = [k for k in keywords if re.search(r"[가-힣]", k)]
    pool = korean_keywords if len(korean_keywords) >= 2 else keywords

    picked = random.sample(pool, k=2) if len(pool) >= 2 else (pool or ["잡학", "TMI"])
    k1 = picked[0]
    k2 = picked[1] if len(picked) > 1 else picked[0]

    openers = [
        "툭 던지는",
        "쓱 꺼내는",
        "탁 치는",
        "살짝 과장한",
    ]
    closers = [
        "아무튼 오늘은 여기까지!",
        "아무튼 그렇다더라!",
        "아무튼 다음에 또 툭!",
        "아무튼 뇌가 간질간질하죠?",
    ]

    opener = random.choice(openers)
    closer = random.choice(closers)

    return (
        f"{opener} {category} 잡학 한 토막! "
        f"{k1} 얘기만 하다 보면 {k2}가 슬쩍 튀어나오는데, 그 순간이 은근히 짜릿하다더라요. "
        f"다음에 {k1} 떠오르면 '아 그거!' 하고 피식 웃어봐요, {closer}"
    ).strip()

async def summarize_with_llm(items: List[dict]) -> Optional[str]:
    """
    원격 LLM을 사용하여 여러 알림을 요약한다.
    items: [{"text": "...", "sender": "..."}, ...]
    알람이 없을 때는 LLM이 랜덤으로 재미있는 말을 한다.
    Returns: 요약 메시지, 또는 None (전송 스킵)
    """
    llm_service = LLMService.get_instance()
    
    if not llm_service.is_loaded():
        if not items:
            return "🤖 LLM 모델이 로드되지 않았습니다... 알람도 없고, 모델도 없네요 😅"
        return "\n".join([f"- [{item['sender']}] {item['text']}" for item in items])
    
    # 알람이 없을 때: 재미있는 말 하기 모드 (10분 간격으로만)
    if not items:
        now = datetime.now()
        current_minute = now.minute

        # 기본 정책: :00, :10, :20, :30, :40, :50만 전송
        should_send = (current_minute % 10 == 0)
        if not should_send:
            # 예외(캐치업): 스케줄러 지연/겹침으로 10분 슬롯을 통째로 놓치면 다음 5분 틱에서 1회 보완 전송
            last_sent = _load_last_random_topic_sent_at()
            if last_sent and (now - last_sent) >= timedelta(minutes=12):
                should_send = True
                logger.info(
                    "No alarms; random topic catch-up enabled "
                    f"(last_sent_at={last_sent.isoformat(timespec='seconds')}, now={now.isoformat(timespec='seconds')})"
                )

        if not should_send:
            logger.info("No alarms; skip random message (not 10-min interval)")
            return None  # 메시지 안 보냄
        
        # 매 시간 정각(:00)에 LLM 세션 리셋 (주제 집착 방지)
        if current_minute == 0:
            llm_service.reset_context()
            logger.info("Hourly LLM context reset performed.")
        
        # 카테고리와 형식을 완전 랜덤으로 선택 (다양성 확보)
        categories = [
            "우주/천문학",
            "물리학/화학",
            "생물학/자연",
            "역사/문화",
            "기술/엔지니어링",
            "수학/논리",
            "심리학/뇌과학",
            "게임/e스포츠",
            "영화/드라마/음악",
            "언어유희/드립",
            "음식/요리",
            "지리/여행",
        ]
        
        # 문장 시작 형식도 랜덤
        formats = [
            "질문형으로 시작해라",
            "팩트 단언형으로 시작해라",
            "감탄형으로 시작해라",
            "수수께끼/퀴즈형으로 시작해라",
            "뉴스속보형으로 시작해라",
            "TMI형으로 시작해라",
        ]
        
        # 최근 카테고리와 중복되지 않도록 선택 (최근 3개 제외)
        recent = _load_recent_categories()
        available_categories = [c for c in categories if c not in recent]
        if not available_categories:  # 모두 최근에 사용된 경우 전체에서 선택
            available_categories = categories
        forced_category = random.choice(available_categories)
        forced_format = random.choice(formats)

        must_keywords = _pick_keywords_for_constraints(forced_category, count=4)
        avoid_keywords = []
        if not ("우주" in forced_category or "천문" in forced_category):
            avoid_keywords = list(_SPACE_KEYWORDS)
        
        # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
        prompt_content = load_prompt(
            "random_topic",
            category=forced_category,
            format=forced_format,
            must_keywords=", ".join(must_keywords),
            avoid_keywords=", ".join(avoid_keywords) if avoid_keywords else "해당 없음",
        )
        if not prompt_content:
            # 폴백: 파일이 없으면 기본 메시지
            return "🤔 오늘도 심심한 하루... 뭐 재미있는 거 없나?"
        
        messages = [
            {
                "role": "user",
                "content": prompt_content
            }
        ]
        
        for attempt in range(3):
            logger.info(f"Generating random wisdom (Attempt {attempt + 1}/3)...")
            try:
                result = await generate_with_main_llm_async(
                    messages,
                    max_tokens=512,
                    temperature=0.7,
                    stop=None
                )
            except Exception as e:
                logger.warning(f"Random wisdom generation failed (Attempt {attempt+1}/3): {e}")
                continue
            result = clean_exaone_tokens(result)
            dump_llm_draft("random_wisdom_draft", result)
            logger.info(f"🔍 [Random Wisdom Draft] Attempt {attempt+1} generated (len={len(result)})")
            
            if not result:
                continue

            # 길이 레일: 170자 이상 280자 이하 (너무 짧거나 길면 재시도)
            MIN_CHARS = 100
            MAX_CHARS = 350
            txt_len = len(result.strip())
            
            if txt_len < MIN_CHARS or txt_len > MAX_CHARS:
                logger.warning(f"Attempt {attempt+1}: Length out of range ({txt_len}). Retrying...")
                continue
                
            korean_ratio = _get_korean_ratio(result)
            
            # 한국어 비율이 낮을 때만 2차 정제 (영어 섞일 때만) - 위트/환각 보존
            needs_refine = korean_ratio < 0.6
            
            final_result = result
            if needs_refine:
                logger.info(f"✂️ Attempt {attempt+1}: Refining with Low-Temp (0.0)...")
                final_result = await refine_draft_with_light_llm_async(
                    prompt_key="refine_random_wisdom",
                    draft=result,
                    temperature=0.0,
                    dump_tag="random_wisdom_refined",
                    clean_meta=True
                )
                logger.info(f"✨ Attempt {attempt+1}: Refined Output: {final_result}")
            else:
                # 정제 안 할 때도 최소한의 메타 헤더는 제거 (LO 추천 ✨)
                final_result = clean_meta_headers(final_result)

            # 우주/천문학 카테고리가 아닐 때 우주 키워드가 튀면 재시도
            if _is_space_drift(final_result, forced_category):
                logger.warning(f"🌌 Attempt {attempt+1}: Space drift detected for category '{forced_category}'. Retrying...")
                continue

            # 카테고리 핵심 키워드가 없으면 재시도
            if not _has_category_anchor(final_result, forced_category):
                logger.warning(f"🧭 Attempt {attempt+1}: Missing category anchor for '{forced_category}'. Retrying...")
                continue
            
            # 최종 한국어 비율 검증 (0.5 이상이어야 통과)
            final_ratio = _get_korean_ratio(final_result)
            if final_ratio >= 0.5:
                logger.info(f"✅ Attempt {attempt+1} Success! Korean Ratio: {final_ratio:.2f}")
                _save_recent_category(forced_category)
                _save_last_random_topic_sent_at(now)
                return final_result.strip()
            else:
                logger.warning(f"❌ Attempt {attempt+1} Failed. Korean Ratio: {final_ratio:.2f}. Retrying...")

        logger.error("All 3 attempts to generate clean random wisdom failed.")
        fallback = _build_random_topic_fallback(forced_category)
        _save_recent_category(forced_category)
        _save_last_random_topic_sent_at(now)
        return fallback

    
    # 알림 목록 구성 (발신자 포함, 중복 제거 로직 강화)
    notification_list = []
    seen_notifications = set()  # (source, text) 중복 체크용
    
    for item in items:
        source = infer_source(item)
        title = item.get('app_title') or ""
        conv = item.get('conversation') or ""
        text = (item.get('text') or "").strip()
        
        # 본문이 비어있으면 스킵 (LO 추천 🧹)
        if not text:
            continue
        
        # Tasker 변수가 치환 안 된 경우 제외
        if title.startswith('%'): title = ""
        if conv.startswith('%'): conv = ""
        
        # 중복 체크 키 (출처와 본문이 같으면 중복으로 간주)
        identifier = (source, text)
        if identifier in seen_notifications:
            continue
        seen_notifications.add(identifier)
        
        context = f"[앱: {source}]"
        if title: context += f" 제목: {title}"
        if conv: context += f" 발신/대화: {conv}"
        
        notification_list.append(f"- {context} 본문: {text}")

    # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
    if not notification_list:
        logger.info("No new notifications to summarize after deduplication/filtering.")
        return None

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
    
    # 보안: 프롭프트는 로그에 찍지 않음 (민감정보 노출 방지)
    total_prompt_len = sum(len(m['content']) for m in messages)
    logger.info(f"LLM Prompt total length: {total_prompt_len} characters")
    result = await generate_with_main_llm_async(messages, max_tokens=512, stop=STOP_TOKENS)
    dump_llm_draft("alarm_summary_draft", result)
    logger.info(f"LLM draft generated (len={len(result or '')})")
    
    # 1단계: 환각 제거 및 특수 토큰 제거
    result = sanitize_llm_output(items, result)
    result = clean_exaone_tokens(result)
    
    # 2단계: 경량 LLM으로 사고과정/메타 설명 정제 (Qwen3-0.6B) - 공통 엔진 사용
    if result and result.strip():
        result = await refine_draft_with_light_llm_async(
            prompt_key="refine_alarm_summary",
            draft=result,
            temperature=0.3,
            dump_tag="alarm_summary_refined",
            clean_meta=True
        )
        logger.info(f"LLM refined (len={len(result)})")
    
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
    result = await generate_with_main_llm_async(messages, max_tokens=256, stop=STOP_TOKENS)
    return clean_exaone_tokens(result)
