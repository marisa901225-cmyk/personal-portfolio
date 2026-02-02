# backend/services/alarm/llm_logic.py
"""LLM을 이용한 알림 요약 및 랜덤 메시지 생성"""
import logging
import re
import json
import random
from datetime import datetime, timedelta
from typing import List, Optional

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
    build_random_topic_fallback,
    build_alarm_summary_fallback,
)

logger = logging.getLogger(__name__)


def _get_korean_ratio(text: str) -> float:
    """텍스트의 한국어 비율을 계산한다."""
    if not text:
        return 0
    korean_chars = len(re.findall(r'[가-힣]', text))
    meaningful_chars = len(re.findall(r'[가-힣a-zA-Z0-9]', text))
    if meaningful_chars == 0:
        return 0
    return korean_chars / meaningful_chars

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
            last_sent = load_last_random_topic_sent_at()
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
        import random
        
        # 최근 카테고리와 중복되지 않도록 선택 (최근 3개 제외)
        all_categories = get_all_categories()
        formats = get_formats()
        
        recent = load_recent_categories()
        recent_clean = [c.strip() for c in recent]
        available_categories = [c for c in all_categories if c.strip() not in recent_clean]
        
        logger.info(f"🔍 Recent categories: {recent_clean}")
        
        if not available_categories:
            logger.warning("All categories were recently used! Resetting selection pool.")
            available_categories = all_categories

        # 확률 기반 선택 (SystemRandom 사용으로 더 고른 분포 보장)
        rng = random.SystemRandom()
        
        # 1. 캐릭터(Voice) 선택
        voices = get_voices()
        voice_names = list(voices.keys())
        forced_voice = rng.choice(voice_names)
        voice_rule = voices[forced_voice]

        # 2. 카테고리 선택 (가중치 관리 로직 뼈대 유지)
        weights = [1.0] * len(available_categories)
        forced_category = rng.choices(available_categories, weights=weights, k=1)[0]
        forced_format = rng.choice(formats)
        
        logger.info(f"🎯 Candidates pool ({len(available_categories)}): {available_categories}")
        logger.info(f"🎲 Topic: '{forced_category}', Voice: '{forced_voice}', Format: '{forced_format}'")

        must_keywords = pick_keywords_for_constraints(forced_category, count=4)
        rng.shuffle(must_keywords)  # ✅ 키워드 순서 셔플로 첫 단어 고정 현상 방지

        # 디버깅을 위한 메타데이터 덤프
        dump_llm_draft("random_wisdom_meta", json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "forced_category": forced_category,
            "forced_voice": forced_voice,
            "forced_format": forced_format,
            "must_keywords": must_keywords,
            "pool_size": len(available_categories),
            "recent_clean": recent_clean
        }, ensure_ascii=False))
        
        # 최근 카테고리들의 모든 키워드를 피해야 할 키워드로 설정
        category_kw_map = get_category_keywords()
        avoid_list = []
        for rc in recent_clean:
            avoid_list.extend(category_kw_map.get(rc, []))
        avoid_keywords_str = ", ".join(list(set(avoid_list))[:15]) # 중복 제거 후 상위 15개만

        # 캐시 효율을 위해 system(불변)/user(가변) 분리
        system_prompt = load_prompt("random_topic_system", voice=forced_voice, voice_rule=voice_rule)
        user_prompt = load_prompt(
            "random_topic_user",
            voice=forced_voice,
            category=forced_category,
            format=forced_format,
            must_keywords=", ".join(must_keywords),
            avoid_keywords=avoid_keywords_str
        )
        if not system_prompt or not user_prompt:
            # 폴백: 파일이 없으면 기본 메시지
            return mark_fallback("🤔 오늘도 심심한 하루... 뭐 재미있는 거 없나?")
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        for attempt in range(2):
            logger.info(f"Generating random wisdom (Attempt {attempt + 1}/2)...")
            try:
                result = await generate_with_main_llm_async(
                    messages,
                    max_tokens=512,
                    temperature=0.85,
                    stop=None,
                    enable_thinking=False  # 랜덤 메시지는 thinking 불필요
                )
            except Exception as e:
                err_msg = str(e).lower()
                if "timeout" in err_msg:
                    logger.error(f"🚨 타임아웃 타임아웃 🚨 (Attempt {attempt+1}/2): {e}")
                else:
                    logger.warning(f"Random wisdom generation failed (Attempt {attempt+1}/2): {e}")
                continue
            result = clean_exaone_tokens(result)
            dump_llm_draft("random_wisdom_draft", result)
            logger.info(f"🔍 [Random Wisdom Draft] Attempt {attempt+1} generated (len={len(result)})!")
            
            if not result:
                continue

            # 길이 레일: 100자 이상 450자 이하
            MIN_CHARS = 100
            MAX_CHARS = 450
            txt_len = len(result.strip())
            
            if txt_len < MIN_CHARS or txt_len > MAX_CHARS:
                logger.warning(f"Attempt {attempt+1}: Length out of range ({txt_len}). Retrying...")
                continue
                
            korean_ratio = _get_korean_ratio(result)
            
            # 한국어 비율이 지나치게 낮을 때만 2차 정제 (중국어 환각 대비)
            needs_refine = korean_ratio < 0.7
            
            final_result = result
            if needs_refine:
                logger.info(f"✂️ Attempt {attempt+1}: Refining with Light LLM (korean_ratio={korean_ratio:.2f})...")
                final_result = await refine_draft_with_light_llm_async(
                    prompt_key="refine_random_wisdom",
                    draft=result,
                    temperature=0.0,
                    dump_tag="random_wisdom_refined",
                    clean_meta=True
                )
            else:
                final_result = clean_meta_headers(final_result)
            
            logger.info(f"✨ Attempt {attempt+1}: Final result (len={len(final_result)})")

            # 카테고리 핵심 키워드가 없으면 재시도
            if not has_category_anchor(final_result, forced_category):
                logger.warning(f"🧭 Attempt {attempt+1}: Missing category anchor for '{forced_category}'. Retrying...")
                continue
            
            # 최종 한국어 비율 검증 (0.8 이상이어야 통과)
            final_ratio = _get_korean_ratio(final_result)
            if final_ratio >= 0.8:
                logger.info(f"✅ Attempt {attempt+1} Success! Korean Ratio: {final_ratio:.2f}")
                save_recent_category(forced_category)
                save_last_random_topic_sent_at(now)
                return final_result.strip()
            else:
                logger.warning(f"❌ Attempt {attempt+1} Failed. Korean Ratio: {final_ratio:.2f}. Retrying...")

        logger.error("All 2 attempts to generate clean random wisdom failed. Using fallback.")
        fallback = build_random_topic_fallback(forced_category)
        save_recent_category(forced_category)
        save_last_random_topic_sent_at(now)
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
    
    # 환각 방지 강화: temperature 더 낮추고 stop 토큰 추가
    enhanced_stop_tokens = (STOP_TOKENS or []) + [
        "\n\n\n",  # 과도한 줄바꿈
        "...",     # 생각 중
        "aaaa", "xxxx", "----",  # 반복 패턴
    ]
    
    result = await generate_with_main_llm_async(
        messages, 
        max_tokens=512,  # 상세 정보를 포함할 수 있도록 토큰 수 확장
        temperature=0.05,  # 거의 greedy decoding
        stop=enhanced_stop_tokens, 
        enable_thinking=False
    )
    dump_llm_draft("alarm_summary_draft", result)
    logger.info(f"LLM draft generated (len={len(result or '')})")
    
    # 1단계: 환각 제거 및 특수 토큰 제거
    result = sanitize_llm_output(items, result)
    result = clean_exaone_tokens(result)

    def _extract_strong_tokens(text: str) -> set[str]:
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

    def _looks_like_count_only_summary(text: str) -> bool:
        """
        '메일 3건'처럼 카운트만 있고 구체적인 제목/본문 단서가 없는 요약을 감지한다.
        - 프롬프트에서 N건 요약을 허용하더라도, 사용자 입장에서는 요약에 "내용"이 필요하므로 폴백한다.
        """
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
            # contains a count
            if not re.search(r"\b\d+\s*건\b", ln):
                continue
            # if the line includes any strong token from originals, it's fine
            line_tokens = _extract_strong_tokens(ln)
            # 부분 일치(포함 관계) 검사로 더욱 유연하게 대응
            if any(any(lt in ot or ot in lt for ot in original_tokens) for lt in line_tokens):
                continue
            
            # 배송, 배달, 업데이트 등 주요 키워드가 포함되어 있으면 요약으로 간주
            important_keywords = {"배송", "택배", "배달", "업데이트", "도착", "완료", "결제", "충전", "메시지"}
            if any(kw in ln for kw in important_keywords):
                continue

            # too generic -> treat as count-only
            return True
        return False

    def _is_weak_summary(text: str) -> bool:
        if not text or not text.strip():
            return True
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return True
        if len(" ".join(lines)) < 6:
            return True
        if len(lines) == 1:
            only = re.sub(r"^[-•*]\\s*", "", lines[0]).strip()
            if only in {"아니다", "없다", "없음", "없습니다", "없어요"}:
                return True
        return False

    used_fallback = False
    if _is_weak_summary(result) or _looks_like_count_only_summary(result):
        logger.warning(f"LLM summary filtering triggered (weak or count-only). Using fallback. Result was: {repr(result)}")
        result = build_alarm_summary_fallback(items)
        used_fallback = True
    
    # 2단계: 메타 헤더만 제거 (경량 LLM 정제 스킵)
    # 이유: 알림 요약은 여러 bullet point를 포함하는데, 경량 LLM이 과도하게 축약하여 중요 내용을 제거하는 문제 발생
    # 메인 LLM의 1차 요약이 이미 충분히 좋으므로 메타 정보만 정리
    if result and result.strip() and not used_fallback:
        result = clean_meta_headers(result)
        logger.info(f"Alarm summary meta headers cleaned (len={len(result)})")

    if used_fallback:
        return mark_fallback(result)

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
    result = await generate_with_main_llm_async(messages, max_tokens=256, stop=STOP_TOKENS, enable_thinking=False)
    return clean_exaone_tokens(result)
