# backend/services/alarm/llm_logic.py
"""LLM을 이용한 알림 요약 및 랜덤 메시지 생성"""
import logging
import re
import json
import random
from datetime import datetime, timedelta
from typing import List, Optional

from .sanitizer import infer_source, sanitize_llm_output, clean_exaone_tokens, get_korean_ratio
from ..prompt_loader import load_prompt
from ..llm_service import LLMService
from .llm_refiner import (
    STOP_TOKENS,
    generate_with_main_llm_async,
    refine_draft_with_light_llm_async,
    dump_llm_draft,
    clean_meta_headers
)
from .random_categories import (
    get_all_categories,
    get_formats,
    load_recent_categories,
    save_recent_category,
    load_last_random_topic_sent_at,
    save_last_random_topic_sent_at,
    pick_keywords_for_constraints,
    has_category_anchor,
    get_voices,
    get_category_keywords,
)

from .fallback_logic import (
    FALLBACK_TAG,
    mark_fallback,
    build_alarm_summary_fallback,
)

logger = logging.getLogger(__name__)


def _extract_strong_tokens(text: str) -> set[str]:
    """텍스트에서 구체적인 정보(숫자 포함 단어, 2자 이상의 한글 등)를 추출한다."""
    tokens = set()
    for tok in re.findall(r"[가-힣A-Za-z0-9_*]+", text or ""):
        if "*" in tok or any(ch.isdigit() for ch in tok):
            tokens.add(tok)
            continue
        if re.search(r"[가-힣]", tok):
            if len(tok) >= 2:
                tokens.add(tok)
            continue
        if len(tok) >= 3:
            tokens.add(tok)
    return tokens


def _looks_like_count_only_summary(text: str, items: List[dict]) -> bool:
    """단순 카운트만 포함한 무성의한 요약인지 검사한다."""
    if not text or not text.strip():
        return False

    original_body = " ".join(
        " ".join(
            [
                (it.get("app_title") or "").strip(),
                (it.get("conversation") or "").strip(),
                (it.get("text") or "").strip(),
            ]
        )
        for it in items
    )
    original_tokens = _extract_strong_tokens(original_body)
    if not original_tokens:
        return False

    for ln in [l.strip() for l in text.splitlines() if l.strip()]:
        if not ln.startswith(("-", "•", "*")):
            continue
        if not re.search(r"\b\d+\s*건\b", ln):
            continue
        line_tokens = _extract_strong_tokens(ln)
        if any(any(lt in ot or ot in lt for ot in original_tokens) for lt in line_tokens):
            continue
        
        important_keywords = {"배송", "택배", "배달", "업데이트", "도착", "완료", "결제", "충전", "메시지"}
        if any(kw in ln for kw in important_keywords):
            continue
        return True
    return False


def _is_weak_summary(text: str) -> bool:
    """요약 내용이 너무 짧거나 무의미한지 검사한다."""
    if not text or not text.strip():
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    if len(" ".join(lines)) < 6:
        return True
    if len(lines) == 1:
        only = re.sub(r"^[-•*]\s*", "", lines[0]).strip()
        if only in {"아니다", "없다", "없음", "없습니다", "없어요"}:
            return True
    return False


async def _generate_random_message_async(now: datetime) -> Optional[str]:
    """랜덤 메시지 생성 핵심로직 분리"""
    # 매 시간 정각(:00)에 LLM 세션 리셋
    if now.minute == 0:
        LLMService.get_instance().reset_context()
        logger.info("Hourly LLM context reset performed.")

    all_categories = get_all_categories()
    formats = get_formats()
    recent = load_recent_categories()
    recent_clean = [c.strip() for c in recent]
    available_categories = [c for c in all_categories if c.strip() not in recent_clean] or all_categories

    voices = get_voices()
    forced_voice = random.choice(list(voices.keys()))
    voice_rule = voices[forced_voice]
    forced_category = random.choice(available_categories)
    forced_format = random.choice(formats)
    
    logger.info(f"🎲 Topic: '{forced_category}', Voice: '{forced_voice}', Format: '{forced_format}'")

    must_keywords = pick_keywords_for_constraints(forced_category, count=4)
    random.shuffle(must_keywords)

    dump_llm_draft("random_wisdom_meta", json.dumps({
        "ts": now.isoformat(timespec="seconds"),
        "forced_category": forced_category,
        "forced_voice": forced_voice,
        "forced_format": forced_format,
        "must_keywords": must_keywords
    }, ensure_ascii=False))
    
    category_kw_map = get_category_keywords()
    avoid_list = []
    for rc in recent_clean:
        avoid_list.extend(category_kw_map.get(rc, []))
    avoid_keywords_str = ", ".join(list(set(avoid_list))[:15])

    system_prompt = load_prompt("random_topic_system", voice=forced_voice, voice_rule=voice_rule)
    user_prompt = load_prompt(
        "random_topic_user",
        voice=forced_voice,
        category=forced_category,
        format=forced_format,
        must_keywords=", ".join(must_keywords) if must_keywords else "(없음, 카테고리에 맞춰 자유롭게 창작)",
        avoid_keywords=avoid_keywords_str if avoid_keywords_str else "(없음)"
    )
    if not system_prompt or not user_prompt:
        return mark_fallback("🤔 오늘도 심심한 하루... 뭐 재미있는 거 없나?")
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    for attempt in range(2):
        logger.info(f"Generating random wisdom (Attempt {attempt+1}/2)...")
        try:
            result = await generate_with_main_llm_async(messages, max_tokens=512, temperature=0.85, enable_thinking=False)
        except Exception as e:
            logger.warning(f"Random wisdom generation failed (Attempt {attempt+1}/2): {e}")
            continue

        result = clean_exaone_tokens(result)
        dump_llm_draft("random_wisdom_draft", result)
        
        if not result: continue

        # 길이 및 한국어 비율 검증
        txt_len = len(result.strip())
        if not (100 <= txt_len <= 450):
            logger.warning(f"Attempt {attempt+1}: Length out of range ({txt_len}).")
            continue
            
        korean_ratio = get_korean_ratio(result)
        final_result = result
        
        if korean_ratio < 0.7:
            logger.info(f"✂️ Attempt {attempt+1}: Refining (ratio={korean_ratio:.2f})...")
            final_result = await refine_draft_with_light_llm_async(
                prompt_key="refine_random_wisdom", draft=result, temperature=0.0, dump_tag="random_wisdom_refined"
            )
        else:
            final_result = clean_meta_headers(final_result)
        
        if not has_category_anchor(final_result, forced_category):
            logger.warning(f"🧭 Attempt {attempt+1}: Missing category anchor for '{forced_category}'.")
            continue
        
        if get_korean_ratio(final_result) >= 0.8:
            logger.info(f"✅ Attempt {attempt+1} Success!")
            save_recent_category(forced_category)
            save_last_random_topic_sent_at(now)
            return final_result.strip()

    err_msg = f"⚠️ 랜덤 메시지 생성 실패 (2회 시도 모두 실패)\n- 카테고리: {forced_category}"
    logger.error(f"All 2 attempts failed for '{forced_category}'. Sending error message notification.")
    return err_msg


def _build_notification_list(items: List[dict]) -> List[str]:
    """알림 항목들을 가공하고 중복을 제거하여 리스트로 만든다."""
    notification_list = []
    seen_notifications = set()
    
    for item in items:
        source = infer_source(item)
        text = (item.get('text') or "").strip()
        if not text: continue
        
        title = item.get('app_title') or ""
        conv = item.get('conversation') or ""
        if title.startswith('%'): title = ""
        if conv.startswith('%'): conv = ""
        
        # 중복 체크 (출처 + 본문)
        if (source, text) in seen_notifications:
            continue
        seen_notifications.add((source, text))
        
        context = f"[앱: {source}]"
        if title: context += f" 제목: {title}"
        if conv: context += f" 발신: {conv}"
        notification_list.append(f"- {context} 본문: {text}")
        
    return notification_list


async def summarize_with_llm(items: List[dict], model: Optional[str] = None, **llm_kwargs) -> Optional[str]:
    """원격 LLM을 사용하여 알림 요약 또는 랜덤 메시지를 생성한다."""
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        if not items: return "🤖 LLM 모델 미로드"
        return "\n".join([f"- [{item['sender']}] {item['text']}" for item in items])
    
    # 1. 알람이 없을 때: 랜덤 메시지 모드
    if not items:
        now = datetime.now()
        should_send = (now.minute % 10 == 0)
        if not should_send:
            last_sent = load_last_random_topic_sent_at()
            if last_sent and (now - last_sent) >= timedelta(minutes=12):
                should_send = True
        
        if not should_send:
            return None
        
        return await _generate_random_message_async(now)
    
    # 2. 알람이 있을 때: 요약 모드
    notification_list = _build_notification_list(items)
    if not notification_list:
        return None

    notifications_str = "\n".join(notification_list)
    prompt_content = load_prompt("alarm_summary", notifications=notifications_str) or f"알림 요약:\n{notifications_str}"
    
    # 환각 방지 설정
    enhanced_stop_tokens = (STOP_TOKENS or []) + ["\n\n\n", "...", "aaaa", "----"]
    
    result = await generate_with_main_llm_async(
        [{"role": "user", "content": prompt_content}], 
        max_tokens=llm_kwargs.get("max_tokens", 512),
        temperature=llm_kwargs.get("temperature", 0.05),
        stop=enhanced_stop_tokens, 
        enable_thinking=llm_kwargs.get("enable_thinking", False),
        model=model,
        **{k: v for k, v in llm_kwargs.items() if k not in ("max_tokens", "temperature", "enable_thinking")}
    )
    dump_llm_draft("alarm_summary_draft", result)
    
    # 정제
    result = sanitize_llm_output(items, result)
    result = clean_exaone_tokens(result)

    used_fallback = False
    if _is_weak_summary(result) or _looks_like_count_only_summary(result, items):
        logger.warning(f"LLM summary filtering triggered. Using fallback. Original: {repr(result)}")
        result = build_alarm_summary_fallback(items)
        used_fallback = True
    else:
        result = clean_meta_headers(result)

    return mark_fallback(result) if used_fallback else result


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
    result = await generate_with_main_llm_async(messages, max_tokens=256, stop=STOP_TOKENS, enable_thinking=False)
    return clean_exaone_tokens(result)
