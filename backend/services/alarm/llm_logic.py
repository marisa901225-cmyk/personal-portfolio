import logging
import os
import json
from datetime import datetime
from typing import List, Optional

from .sanitizer import infer_source, escape_html_preserve_urls, sanitize_llm_output, clean_exaone_tokens
from ..prompt_loader import load_prompt
from ..llm_service import LLMService

logger = logging.getLogger(__name__)

def parse_json_response(text: str) -> Optional[List[str]]:
    import re
    start_idx = text.find('[')
    end_idx = text.rfind(']')
    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return None
    json_str = text[start_idx:end_idx+1].strip()
    json_str = re.sub(r'[\x00-\x1F\x7F]', '', json_str)
    if "```" in json_str:
        json_str = re.sub(r'```[a-zA-Z]*', '', json_str).strip()
    try:
        return json.loads(json_str)
    except Exception:
        temp_str = json_str
        while True:
            last_bracket = temp_str.rfind(']')
            if last_bracket == -1: break
            temp_str = temp_str[:last_bracket+1]
            try:
                clean_str = re.sub(r'[\x00-\x1F\x7F]', '', temp_str)
                phrases = json.loads(clean_str)
                if isinstance(phrases, list): return phrases
            except:
                temp_str = temp_str[:-1]
    return None

def generate_idle_message(llm_service) -> Optional[str]:
    current_minute = datetime.now().minute
    if current_minute % 10 != 0:
        logger.info(f"No alarms, but skipping random message (minute={current_minute})")
        return None
    if current_minute == 0:
        llm_service.reset_context()
        logger.info("Hourly LLM context reset performed.")
    
    category_index = (current_minute // 5) % 4
    format_index = (datetime.now().hour + category_index) % 5
    
    categories = [
        "지식/과학 (우주, 물리학, 생물학, 기술사, 수학 퍼즐)",         # 랜덤 토픽
        "역사/문화 (고대문명, 이상한 역사, 폐기된 발명품, 기묘한 법률)",  # 잡학사전
        "인문/예술 (명화 속 숨겨진 상징, 위대한 작가의 기행, 고전의 새로운 해석)", # 예술 & 미스터리
        "철학/심리 (사고실험, 인지 편향, 재미있는 통계, 언어유희)"      # 심심풀이 지식
    ]
    formats = [
        "팩트 단언형으로 시작해라 (예: '사실...' / '진짜 신기한 건...')",
        "질문형으로 시작해라 (예: '혹시 알아?' / '이거 들어봤어?')",
        "감탄형으로 시작해라 (예: '와!' / '헐!' / '대박!')",
        "수수께끼/퀴즈형으로 시작해라 (예: 'OO는 왜 OO일까?')",
        "뉴스 속보형으로 시작해라 (예: '[속보] 알고보니 OO가...') "
    ]
    
    prompt = load_prompt("random_topic", category=categories[category_index], format=formats[format_index])
    if not prompt: return "🤔 오늘도 심심한 하루... 뭐 재미있는 거 없나?"
    
    logger.info("No alarms to process. Asking LLM for random wisdom (structured RE2)...")
    # 구조적 RE2: 1.7B 경량 모델에 맞게 단순 반복 대신 "지시→주의→실행" 구조 사용
    structured_prompt = f"""[지시사항]
{prompt}

[주의]
반드시 위 지시사항을 두 번 확인하고, '아하'나 '음' 같은 서두 없이 결과만 출력해라.

[실행 결과]"""
    
    # 1단계: 초안 생성 (stop sequence로 COT 시작 시 즉시 차단, temperature 하향)
    draft = llm_service.generate_chat(
        [{"role": "user", "content": structured_prompt}],
        max_tokens=256,
        temperature=0.7,
        stop=["아하", "음,", "사용자가", "지시사항을"]
    )
    # COT 제거 적용
    draft = clean_exaone_tokens(draft)
    logger.info(f"[DEBUG] Draft Response: {draft[:100]}...")

    # 2단계: 다듬기 필요 여부 판단 (이상한 영어가 많거나 너무 짧은 경우 등)
    if _is_refinement_needed(draft):
        refine_prompt = load_prompt("refine_message", draft=draft)
        if refine_prompt:
            logger.info("Refinement triggered: Draft was messy or mostly English.")
            result = llm_service.generate_chat(
                [{"role": "user", "content": refine_prompt}],
                max_tokens=128,
                temperature=0.7,
                stop=["Okay", "let me", "Let me", "I'll", "아하", "음,", "사용자가"]
            )
            result = clean_exaone_tokens(result)
            logger.info(f"[DEBUG] Refined Response: {result[:100]}...")
            # Refinement 결과도 여전히 실패면 fallback
            if _is_refinement_needed(result):
                logger.warning("Refinement also failed. Returning fallback message.")
                return None  # process_pending_alarms에서 None은 전송 스킵됨
            return result
    else:
        logger.info("Draft is clean and mostly Korean. Skipping refinement.")
        return draft
    
    return draft

def _is_refinement_needed(text: str) -> bool:
    """초안이 다듬기가 필요한지(영어가 너무 많거나 비었는지 등) 판단"""
    if not text or len(text.strip()) < 10:
        return True
    
    # 한글 문자 수 계산
    import re
    korean_chars = len(re.findall(r'[ㄱ-ㅎ가-힣]', text))
    # 전체 텍스트 중 한글 비율이 40% 미만이면 영어나 메타데이터 위주로 판단 (실패 사례)
    korean_ratio = korean_chars / len(text)
    
    if korean_ratio < 0.4:
        logger.warning(f"Low Korean ratio detected ({korean_ratio:.2f}). Refinement highly recommended.")
        return True
        
    return False

def _check_llm_server_health(llm_service) -> str:
    """LLM 서버 상태 확인: 'ok', 'loading', 'unreachable' 중 하나 반환"""
    if not llm_service._is_remote_mode():
        return "ok" if llm_service._model else "unreachable"
    
    try:
        import httpx
        base_url = llm_service._base_url
        if not base_url:
            return "unreachable"
        response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=3)
        if response.status_code == 200:
            data = response.json()
            # llama-server는 모델 로딩 중에도 200을 반환할 수 있음
            # 일부 서버는 status 필드를 포함
            status = data.get("status", "ok")
            if status in ["loading", "model_loading"]:
                return "loading"
            return "ok"
        elif response.status_code == 503:
            return "loading"
        return "unreachable"
    except Exception:
        return "unreachable"

def _basic_alarm_summary(items: List[dict], max_lines: int = 6, max_chars: int = 80) -> Optional[str]:
    """
    LLM 요약이 비어있거나 환각으로 제거된 경우를 위한 안전한 폴백.
    입력 알림 본문을 그대로(마스킹 유지) 짧게 나열한다.
    """
    lines: List[str] = []
    for it in items:
        text = (it.get("text") or "").strip()
        if not text:
            continue
        source = infer_source(it)
        compact = " ".join(text.split())
        if len(compact) > max_chars:
            compact = compact[: max_chars - 1].rstrip() + "…"
        lines.append(f"- [{source}] {compact}")
        if len(lines) >= max_lines:
            break
    return "\n".join(lines).strip() or None

async def summarize_with_llm(items: List[dict]) -> str:
    llm_service = LLMService.get_instance()

    # 알림이 없고 10분 간격이 아니면, 원격 상태 체크/LLM 호출 없이 빠르게 스킵한다.
    if not items and datetime.now().minute % 10 != 0:
        return None
    
    # 서버 상태 확인
    server_status = _check_llm_server_health(llm_service)
    
    if server_status == "loading":
        # 모델 로딩 중이면 조용히 스킵 (폴백 메시지 없음)
        logger.info("LLM server is loading model, skipping this cycle")
        return None
    
    if not llm_service.is_loaded() or server_status == "unreachable":
        # 알림이 없는 사이클에서는 조용히 스킵한다.
        # (원격 LLM 장애/설정 문제로 '랜덤 토픽'이 계속 전송되는 현상 방지)
        if not items:
            logger.info("LLM unavailable and no items; skipping idle message")
            return None
        return _basic_alarm_summary(items)
    
    if not items:
        return generate_idle_message(llm_service)

    meaningful_items = [it for it in items if (it.get("text") or "").strip()]
    if not meaningful_items:
        return None

    notification_list = []
    for item in meaningful_items:
        source = infer_source(item)
        title = (item.get('app_title') or "").replace('%', '')
        conv = (item.get('conversation') or "").replace('%', '')
        text = item.get('text') or ""
        
        context = f"[앱: {source}]"
        if title: context += f" 제목: {title}"
        if conv: context += f" 발신/대화: {conv}"
        notification_list.append(f"- {context} 본문: {text}")

    notifications_str = "\n".join(notification_list)
    prompt_content = load_prompt("alarm_summary", notifications=notifications_str) or f"아래 스마트폰 알림들을 한국어로 요약해줘:\n{notifications_str}"
    
    # 구조적 RE2: 1.7B 경량 모델에 맞게 "지시→주의→실행" 구조 사용
    structured_prompt = f"""[지시사항]
{prompt_content}

[주의]
'아하'나 '음' 같은 서두 없이 요약 결과만 출력해라.

[요약 결과]"""

    # 1단계: 초안 생성 (stop sequence로 COT 시작 시 즉시 차단)
    draft = llm_service.generate_chat(
        [{"role": "user", "content": structured_prompt}],
        max_tokens=512,
        temperature=0.2,
        stop=["아하", "음,", "사용자가"]
    )
    logger.info(f"[DEBUG] Summary Draft (len={len(draft)}): {draft[:100]}...")
    
    draft = sanitize_llm_output(meaningful_items, draft)
    draft = clean_exaone_tokens(draft)

    # 2단계: 다듬기 (Refinement)
    refine_prompt = load_prompt("refine_alarm_summary", draft=draft)
    if refine_prompt:
        logger.info("Refining alarm summary...")
        result = llm_service.generate_chat(
            [{"role": "user", "content": refine_prompt}],
            max_tokens=512,
            temperature=0.1, # 요약 다듬기는 매우 낮은 temperature 선호
        )
        result = clean_exaone_tokens(result)
        logger.info(f"[DEBUG] Refined Summary (len={len(result)}): {result[:100]}...")
        # 환각 등으로 비었으면 Draft를 마지노선으로 사용
        if not result.strip():
            result = draft
    else:
        result = draft

    # 최종 결과가 비었으면 안전한 폴백
    if not result.strip():
        return _basic_alarm_summary(meaningful_items)

    return result

async def summarize_expenses_with_llm(expenses: List[dict]) -> str:
    if not expenses: return ""
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded(): return ""

    expense_list = [f"- {e['merchant']}: {abs(e['amount']):,.0f}원 ({e['category']})" for e in expenses]
    messages = [{"role": "user", "content": f"""You are a financial assistant. Analyze the following payment records and provide a short, witty one-sentence analysis in Korean about the user's spending patterns or characteristics.
Start directly with the result without any introductory phrases or greetings.

[Payments]
{"\n".join(expense_list)}"""}]
    
    result = llm_service.generate_chat(messages, max_tokens=128)
    return clean_exaone_tokens(result)

async def generate_daily_catchphrases(save_path: str):
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded(): return

    prompt_content = load_prompt("daily_esports_catchphrases")
    if not prompt_content:
        prompt_content = "e스포츠 경기 시작 알림 멘트 20개를 JSON 리스트로 생성해줘." # Simplified fallback

    messages = [
        {"role": "user", "content": prompt_content},
        {"role": "assistant", "content": "["}
    ]
    
    result = llm_service.generate_chat(messages, max_tokens=1024, temperature=0.9, stop=["]"])
    if not result.startswith("["): result = "[" + result
    if not result.endswith("]"): result = result + "]"
    
    phrases = parse_json_response(result)
    if phrases:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(phrases, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(phrases)} catchphrases to {save_path}")
