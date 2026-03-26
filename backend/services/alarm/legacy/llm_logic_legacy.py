# backend/services/alarm/llm_logic.py
"""LLM을 이용한 알림 요약 및 랜덤 메시지 생성"""

import logging
import re
import json
import random
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any

from .alarm_keywords import COUNT_ONLY_EXCEPTION_KEYWORDS
from .sanitizer import infer_source, sanitize_llm_output, clean_exaone_tokens, get_korean_ratio
from ..prompt_loader import load_prompt
from ..llm_service import LLMService
from .llm_refiner import (
    STOP_TOKENS,
    generate_with_main_llm_async,
    refine_draft_with_light_llm_async,
    dump_llm_draft,
    clean_meta_headers,
)
from .random_categories import (
    get_all_categories,
    get_formats,
    get_openers,
    get_twists,
    load_recent_categories,
    save_recent_category,
    load_last_random_topic_sent_at,
    save_last_random_topic_sent_at,
    pick_keywords_for_constraints,
    has_category_anchor,
    get_voices,
    get_category_keywords,
)

logger = logging.getLogger(__name__)

_RE_TOKEN = re.compile(r"[가-힣A-Za-z0-9_*]+")
_RE_BULLET_PREFIX = re.compile(r"^[-•*]\s*")
_RE_COUNT_ONLY = re.compile(r"\b\d+\s*건\b")
_RE_WS = re.compile(r"\s+")
_RE_ENGLISH_REASONING = re.compile(
    r"(looking at|the title is|okay[, ]|let's|first[, ]|since there's|so the summary should|i need to)",
    re.IGNORECASE,
)
_RE_NON_KOREAN_CJK = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\u3040-\u30FF\u31F0-\u31FF]")


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _build_stop_tokens(extra: Optional[List[str]] = None) -> List[str]:
    base = list(STOP_TOKENS or [])
    if extra:
        base.extend(extra)
    return _dedupe_keep_order(base)


def _filter_llm_kwargs(llm_kwargs: Dict[str, Any], exclude: Tuple[str, ...]) -> Dict[str, Any]:
    """중복 키워드 인자(TypeError) 방지를 위한 llm_kwargs 필터."""
    return {k: v for k, v in (llm_kwargs or {}).items() if k not in exclude}


def _hourly_reset_llm_context(now: datetime) -> None:
    # 매 시간 정각(:00)에 LLM 세션 리셋
    if now.minute == 0:
        LLMService.get_instance().reset_context()
        logger.info("Hourly LLM context reset performed.")


def _extract_strong_tokens(text: str) -> set[str]:
    """텍스트에서 구체적인 정보(숫자 포함 단어, 2자 이상의 한글 등)를 추출한다."""
    tokens: set[str] = set()
    for tok in _RE_TOKEN.findall(text or ""):
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

    for ln in (l.strip() for l in (text or "").splitlines()):
        if not ln:
            continue
        if not ln.startswith(("-", "•", "*")):
            continue
        if not _RE_COUNT_ONLY.search(ln):
            continue

        # 카운트 문장인데, 원문과 겹치는 강한 토큰이 있으면 "카운트-only"로 보지 않음
        line_tokens = _extract_strong_tokens(ln)
        if any(any(lt in ot or ot in lt for ot in original_tokens) for lt in line_tokens):
            continue

        # 배송/결제 같은 핵심키워드 있으면 카운트-only로 보지 않음
        if any(keyword in ln for keyword in COUNT_ONLY_EXCEPTION_KEYWORDS):
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
        only = _RE_BULLET_PREFIX.sub("", lines[0]).strip()
        if only in {"아니다", "없다", "없음", "없습니다", "없어요"}:
            return True
    return False


def _has_non_korean_meta_output(text: str) -> bool:
    """영어 메타/사고문장 출력이 섞였는지 검사한다."""
    if not text or not text.strip():
        return False

    if _RE_ENGLISH_REASONING.search(text):
        return True

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if not re.search(r"[A-Za-z]", ln):
            continue
        alpha_count = len(re.findall(r"[A-Za-z]", ln))
        if alpha_count < 6:
            continue
        if get_korean_ratio(ln) < 0.25:
            return True
    return False


def _has_non_korean_cjk_chars(text: str) -> bool:
    """한글 외 CJK 문자(한자/가타카나/히라가나) 포함 여부를 검사한다."""
    return bool(_RE_NON_KOREAN_CJK.search(text or ""))


def _has_invalid_bullet_format(text: str) -> bool:
    """요약 결과가 bullet-only 형식을 지키는지 검사한다."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    return any(not ln.startswith(("-", "•", "*")) for ln in lines)


def _build_notification_list(items: List[dict]) -> List[str]:
    """알림 항목들을 가공하고 중복을 제거하여 리스트로 만든다."""
    notification_list: List[str] = []
    seen = set()

    for item in items:
        source = infer_source(item)
        text = (item.get("text") or "").strip()
        if not text:
            continue

        title = (item.get("app_title") or "").strip()
        conv = (item.get("conversation") or "").strip()
        if title.startswith("%"):
            title = ""
        if conv.startswith("%"):
            conv = ""

        key = (source, text)
        if key in seen:
            continue
        seen.add(key)

        payload = {
            "idx": len(notification_list) + 1,
            "app": source,
            "title": title,
            "conversation": conv,
            "body": text,
        }
        notification_list.append(json.dumps(payload, ensure_ascii=False))

    return notification_list


def _postprocess_llm_text(text: str) -> str:
    """공통 후처리: exaone 토큰 정리 + 메타 헤더 제거."""
    text = clean_exaone_tokens(text or "")
    text = clean_meta_headers(text or "")
    return text.strip()


def _validate_alarm_summary(text: str, items: List[dict]) -> Tuple[bool, str]:
    """알림 요약 결과 검증. (실패 시 이유 반환)"""
    if _is_weak_summary(text):
        return False, "요약이 너무 짧거나 무의미함"
    if _has_invalid_bullet_format(text):
        return False, "출력 형식 위반(불릿 형식 아님)"
    if _has_non_korean_meta_output(text):
        return False, "영어 메타/사고문장 포함"
    if _looks_like_count_only_summary(text, items):
        return False, "단순 카운트(몇 건) 나열로 보임"
    return True, ""


def _should_send_random_topic(now: datetime) -> bool:
    # 10분 단위 정각(0,10,20...)에 우선 전송
    if now.minute % 10 == 0:
        return True

    # 혹시 스케줄 드리프트가 있어도 12분 이상 공백이면 보정 전송
    last_sent = load_last_random_topic_sent_at()
    return bool(last_sent and (now - last_sent) >= timedelta(minutes=12))


async def _generate_random_message_async(
    now: datetime,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    """랜덤 메시지 생성"""
    def _compact_reason(reason: str, limit: int = 140) -> str:
        return _RE_WS.sub(" ", (reason or "")).strip()[:limit]

    _hourly_reset_llm_context(now)

    all_categories = get_all_categories()
    formats = get_formats()
    recent = [c.strip() for c in load_recent_categories() if c and c.strip()]
    available_categories = [c for c in all_categories if c.strip() not in set(recent)] or all_categories

    voices = get_voices()
    forced_voice = random.choice(list(voices.keys()))
    voice_rule = voices[forced_voice]
    forced_category = random.choice(available_categories)
    forced_format = random.choice(formats)
    openers = get_openers()
    twists = get_twists()
    forced_opener = random.choice(openers) if openers else ""
    forced_twist = random.choice(twists) if twists else ""

    logger.info(
        "🎲 Topic: '%s', Voice: '%s', Format: '%s', Opener: '%s', Twist: '%s'",
        forced_category,
        forced_voice,
        forced_format,
        forced_opener[:80],
        forced_twist[:80],
    )

    must_keywords = pick_keywords_for_constraints(forced_category, count=4)
    random.shuffle(must_keywords)

    dump_llm_draft(
        "random_wisdom_meta",
        json.dumps(
            {
                "ts": now.isoformat(timespec="seconds"),
                "forced_category": forced_category,
                "forced_voice": forced_voice,
                "forced_format": forced_format,
                "forced_opener": forced_opener,
                "forced_twist": forced_twist,
                "must_keywords": must_keywords,
            },
            ensure_ascii=False,
        ),
    )

    category_kw_map = get_category_keywords()
    avoid_list: List[str] = []
    for rc in recent:
        avoid_list.extend(category_kw_map.get(rc, []))
    avoid_keywords_str = ", ".join(list(set(avoid_list))[:15])

    system_prompt = load_prompt("random_topic_system")
    user_prompt = load_prompt(
        "random_topic_user",
        voice=forced_voice,
        voice_rule=voice_rule,
        category=forced_category,
        format=forced_format,
        opener=forced_opener or "(없음)",
        twist=forced_twist or "(없음)",
        must_keywords=", ".join(must_keywords) if must_keywords else "(없음, 카테고리에 맞춰 자유롭게 창작)",
        avoid_keywords=avoid_keywords_str if avoid_keywords_str else "(없음)",
    )

    # 불필요한 fallback 제거: 프롬프트 없으면 조용히 스킵
    if not system_prompt or not user_prompt:
        logger.warning("Random topic prompt missing. Skip sending random message.")
        return None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # kwargs 충돌 방지
    max_tokens = int(llm_kwargs.get("max_tokens", 512))
    temperature = float(llm_kwargs.get("temperature", 0.85))
    enable_thinking = bool(llm_kwargs.get("enable_thinking", False))
    extra_kwargs = _filter_llm_kwargs(llm_kwargs, exclude=("max_tokens", "temperature", "enable_thinking", "stop"))

    failure_reasons: List[str] = []

    for attempt in range(2):
        attempt_no = attempt + 1
        logger.info(f"Generating random wisdom (Attempt {attempt_no}/2)...")

        try:
            raw = await generate_with_main_llm_async(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                enable_thinking=enable_thinking,
                model=model,
                **extra_kwargs,
            )
        except Exception as e:
            reason = f"{attempt_no}회차: LLM 예외 ({_compact_reason(str(e))})"
            failure_reasons.append(reason)
            logger.warning(f"Random wisdom generation failed (Attempt {attempt_no}/2): {e}")
            continue

        raw = clean_exaone_tokens(raw or "")
        dump_llm_draft("random_wisdom_draft", raw)

        if not raw.strip():
            failure_reasons.append(f"{attempt_no}회차: 응답이 비어 있음")
            continue

        txt_len = len(raw.strip())
        if not (100 <= txt_len <= 600):
            failure_reasons.append(f"{attempt_no}회차: 길이 {txt_len}자 (허용 100~600자)")
            continue

        # 한국어 비율이 낮으면 light LLM으로 정제
        korean_ratio = get_korean_ratio(raw)
        has_non_ko_cjk = _has_non_korean_cjk_chars(raw)
        final_text = raw

        if korean_ratio < 0.7 or has_non_ko_cjk:
            logger.info(
                "✂️ Attempt %s: Refining (ratio=%.2f, non_ko_cjk=%s)...",
                attempt_no,
                korean_ratio,
                has_non_ko_cjk,
            )
            final_text = await refine_draft_with_light_llm_async(
                prompt_key="refine_random_wisdom",
                draft=raw,
                temperature=0.0,
                dump_tag="random_wisdom_refined",
            )
        final_text = _postprocess_llm_text(final_text)

        if not final_text:
            failure_reasons.append(f"{attempt_no}회차: 정제 후 응답이 비어 있음")
            continue

        if not has_category_anchor(final_text, forced_category):
            failure_reasons.append(f"{attempt_no}회차: 카테고리 핵심 키워드 미포함")
            continue

        final_ratio = get_korean_ratio(final_text)
        if final_ratio < 0.8:
            failure_reasons.append(f"{attempt_no}회차: 한국어 비율 {final_ratio:.2f} (< 0.80)")
            continue
        if _has_non_korean_cjk_chars(final_text):
            failure_reasons.append(f"{attempt_no}회차: 한글 외 CJK 문자 포함")
            continue

        # 성공
        save_recent_category(forced_category)
        save_last_random_topic_sent_at(now)
        logger.info(f"✅ Random wisdom success (Attempt {attempt_no}/2)")
        return final_text

    # 불필요한 fallback 제거: 실패 사유는 로그에만 남기고 사용자에게는 아무것도 보내지 않음
    if failure_reasons:
        logger.error(
            "Random wisdom failed after 2 attempts. "
            f"category={forced_category}, reasons={failure_reasons}"
        )
    return None


async def _generate_alarm_summary_async(
    items: List[dict],
    prompt_content: str,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    """알림 요약 생성 (최대 2회 시도, fallback 없이 실패 시 None)."""

    stop = _build_stop_tokens(extra=["\n\n\n", "...", "aaaa", "----"])

    max_tokens = int(llm_kwargs.get("max_tokens", 512))
    temperature = float(llm_kwargs.get("temperature", 0.05))
    enable_thinking = bool(llm_kwargs.get("enable_thinking", False))
    extra_kwargs = _filter_llm_kwargs(llm_kwargs, exclude=("max_tokens", "temperature", "enable_thinking", "stop"))

    # 두 번째 시도는 “카운트-only 금지”를 더 강하게 박음
    extra_guard = (
        "\n\n[추가 규칙]\n"
        "- 'N건'만 나열하지 말고, 각 항목에서 최소 1개의 구체 단서(금액/날짜/상태/키워드/발신자/앱)를 포함해.\n"
        "- 알림에 없는 사실을 만들어내지 마.\n"
    )

    for attempt in range(2):
        attempt_no = attempt + 1
        logger.info(f"Generating alarm summary (Attempt {attempt_no}/2)...")

        content = prompt_content if attempt_no == 1 else (prompt_content + extra_guard)

        raw = await generate_with_main_llm_async(
            [{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
            enable_thinking=enable_thinking,
            model=model,
            **extra_kwargs,
        )
        dump_llm_draft("alarm_summary_draft", raw)

        # 환각 억제/정제
        cleaned = sanitize_llm_output(items, raw or "")
        cleaned = _postprocess_llm_text(cleaned)

        ok, reason = _validate_alarm_summary(cleaned, items)
        if ok:
            return cleaned

        logger.warning(f"Alarm summary rejected (Attempt {attempt_no}/2): {reason}. text={repr(cleaned)}")

    return None


async def summarize_with_llm(items: List[dict], model: Optional[str] = None, **llm_kwargs) -> Optional[str]:
    """원격 LLM을 사용하여 알림 요약 또는 랜덤 메시지를 생성한다."""
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        # 불필요한 장식성 fallback 제거: 랜덤 메시지는 스킵.
        if not items:
            return None
        # LLM이 없을 때도 알림은 최소한 보여주고 싶다면: 정제된 리스트 그대로 반환
        notification_list = _build_notification_list(items)
        return "\n".join(notification_list) if notification_list else None

    # 1) 알람이 없을 때: 랜덤 메시지
    if not items:
        now = datetime.now()
        if not _should_send_random_topic(now):
            return None
        return await _generate_random_message_async(now, model=model, **llm_kwargs)

    # 2) 알람이 있을 때: 요약
    notification_list = _build_notification_list(items)
    if not notification_list:
        return None

    notifications_str = "\n".join(notification_list)
    prompt_content = load_prompt("alarm_summary", notifications=notifications_str) or f"알림 요약:\n{notifications_str}"

    return await _generate_alarm_summary_async(items, prompt_content, model=model, **llm_kwargs)


async def summarize_expenses_with_llm(expenses: List[dict]) -> str:
    """가계부 내역(결제 승인)을 분석하여 짧은 코멘트를 생성한다."""
    if not expenses:
        return ""

    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        return ""

    expense_lines = [
        f"- {e['merchant']}: {abs(e['amount']):,.0f}원 ({e['category']})"
        for e in expenses
    ]

    prompt = (
        "You are a financial assistant. Analyze the following payment records and provide a short, "
        "witty one-sentence analysis in Korean about the user's spending patterns or characteristics.\n"
        "Start directly with the result without any introductory phrases or greetings.\n\n"
        "[Payments]\n"
        + "\n".join(expense_lines)
    )

    result = await generate_with_main_llm_async(
        [{"role": "user", "content": prompt}],
        max_tokens=256,
        stop=_build_stop_tokens(),
        enable_thinking=False,
    )
    return clean_exaone_tokens(result or "").strip()
