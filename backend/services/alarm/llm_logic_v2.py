# backend/services/alarm/llm_logic_v2.py
"""Refactored v2 of alarm LLM logic with the same public API."""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .alarm_keywords import COUNT_ONLY_EXCEPTION_KEYWORDS
from .llm_refiner import (
    STOP_TOKENS,
    clean_meta_headers,
    dump_llm_draft,
    generate_with_main_llm_async,
    refine_draft_with_light_llm_async,
)
from .random_categories import (
    get_all_categories,
    get_category_keywords,
    get_formats,
    get_openers,
    get_twists,
    get_voices,
    has_category_anchor,
    load_last_random_topic_sent_at,
    load_recent_categories,
    pick_keywords_for_constraints,
    save_last_random_topic_sent_at,
    save_recent_category,
)
from .sanitizer import get_korean_ratio, infer_source, sanitize_llm_output
from ..llm_service import LLMService
from ..prompt_loader import load_prompt

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
_RE_RANDOM_TITLE_PREFIX = re.compile(r"^\s*(title|제목)\s*:\s*", re.IGNORECASE)
_REPLACEMENT_CHAR = "\ufffd"


@dataclass(frozen=True, slots=True)
class _LLMRunOptions:
    max_tokens: int
    temperature: float
    enable_thinking: bool
    extra_kwargs: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class _RandomTopicPlan:
    category: str
    voice: str
    voice_rule: str
    format: str
    opener: str
    twist: str
    must_keywords: List[str]
    avoid_keywords: str


@dataclass(frozen=True, slots=True)
class _RandomMessagePayload:
    title: str
    body: str


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for value in items:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _build_stop_tokens(extra: Optional[List[str]] = None) -> List[str]:
    base = list(STOP_TOKENS or [])
    if extra:
        base.extend(extra)
    return _dedupe_keep_order(base)


def _filter_llm_kwargs(llm_kwargs: Dict[str, Any], exclude: Tuple[str, ...]) -> Dict[str, Any]:
    return {key: value for key, value in (llm_kwargs or {}).items() if key not in exclude}


def _resolve_llm_options(
    llm_kwargs: Dict[str, Any],
    *,
    default_max_tokens: int,
    default_temperature: float,
) -> _LLMRunOptions:
    return _LLMRunOptions(
        max_tokens=int(llm_kwargs.get("max_tokens", default_max_tokens)),
        temperature=float(llm_kwargs.get("temperature", default_temperature)),
        enable_thinking=bool(llm_kwargs.get("enable_thinking", False)),
        extra_kwargs=_filter_llm_kwargs(
            llm_kwargs,
            exclude=("max_tokens", "temperature", "enable_thinking", "stop"),
        ),
    )


def _hourly_reset_llm_context(now: datetime) -> None:
    if now.minute == 0:
        LLMService.get_instance().reset_context()
        logger.info("Hourly LLM context reset performed.")


def _extract_strong_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in _RE_TOKEN.findall(text or ""):
        if "*" in token or any(ch.isdigit() for ch in token):
            tokens.add(token)
            continue
        if re.search(r"[가-힣]", token):
            if len(token) >= 2:
                tokens.add(token)
            continue
        if len(token) >= 3:
            tokens.add(token)
    return tokens


def _looks_like_count_only_summary(text: str, items: List[dict]) -> bool:
    if not text or not text.strip():
        return False

    original_body = " ".join(
        " ".join(
            [
                (item.get("app_title") or "").strip(),
                (item.get("conversation") or "").strip(),
                (item.get("text") or "").strip(),
            ]
        )
        for item in items
    )
    original_tokens = _extract_strong_tokens(original_body)
    if not original_tokens:
        return False

    for line in (line.strip() for line in (text or "").splitlines()):
        if not line or not line.startswith(("-", "•", "*")):
            continue
        if not _RE_COUNT_ONLY.search(line):
            continue

        line_tokens = _extract_strong_tokens(line)
        if any(any(line_tok in org_tok or org_tok in line_tok for org_tok in original_tokens) for line_tok in line_tokens):
            continue
        if any(keyword in line for keyword in COUNT_ONLY_EXCEPTION_KEYWORDS):
            continue
        return True

    return False


def _is_weak_summary(text: str) -> bool:
    if not text or not text.strip():
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
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
    if not text or not text.strip():
        return False
    if _RE_ENGLISH_REASONING.search(text):
        return True

    for line in (line.strip() for line in text.splitlines() if line.strip()):
        if not re.search(r"[A-Za-z]", line):
            continue
        alpha_count = len(re.findall(r"[A-Za-z]", line))
        if alpha_count < 6:
            continue
        if get_korean_ratio(line) < 0.25:
            return True
    return False


def _has_non_korean_cjk_chars(text: str) -> bool:
    return bool(_RE_NON_KOREAN_CJK.search(text or ""))


def _has_replacement_char(text: str) -> bool:
    return _REPLACEMENT_CHAR in (text or "")


def _has_invalid_bullet_format(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    return any(not line.startswith(("-", "•", "*")) for line in lines)


def _build_notification_list(items: List[dict]) -> List[str]:
    notification_list: List[str] = []
    seen = set()

    for item in items:
        source = infer_source(item)
        text = (item.get("text") or "").strip()
        if not text:
            continue

        title = (item.get("app_title") or "").strip()
        conversation = (item.get("conversation") or "").strip()
        if title.startswith("%"):
            title = ""
        if conversation.startswith("%"):
            conversation = ""

        dedupe_key = (source, text)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        payload = {
            "idx": len(notification_list) + 1,
            "app": source,
            "title": title,
            "conversation": conversation,
            "body": text,
        }
        notification_list.append(json.dumps(payload, ensure_ascii=False))

    return notification_list


def _postprocess_llm_text(text: str) -> str:
    text = clean_meta_headers(text or "")
    return text.strip()


def _validate_alarm_summary(text: str, items: List[dict]) -> Tuple[bool, str]:
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
    if now.minute % 10 == 0:
        return True
    last_sent = load_last_random_topic_sent_at()
    return bool(last_sent and (now - last_sent) >= timedelta(minutes=12))


def _compact_reason(reason: str, limit: int = 140) -> str:
    return _RE_WS.sub(" ", (reason or "")).strip()[:limit]


def _default_random_title(now: datetime) -> str:
    titles = ["오늘의 브리핑", "읽을거리", "짧은 메모", "오늘의 한 조각", "가벼운 이야기", "생각 한 스푼"]
    return titles[(now.minute // 10) % len(titles)]


def _pick_random_topic_plan() -> _RandomTopicPlan:
    all_categories = get_all_categories()
    formats = get_formats()
    openers = get_openers()
    twists = get_twists()
    recent = [category.strip() for category in load_recent_categories() if category and category.strip()]
    available_categories = [category for category in all_categories if category.strip() not in set(recent)] or all_categories

    voices = get_voices()
    forced_voice = random.choice(list(voices.keys()))
    forced_category = random.choice(available_categories)
    forced_format = random.choice(formats)
    forced_opener = random.choice(openers) if openers else ""
    forced_twist = random.choice(twists) if twists else ""

    must_keywords = pick_keywords_for_constraints(forced_category, count=4)
    random.shuffle(must_keywords)

    category_kw_map = get_category_keywords()
    avoid_list: List[str] = []
    for recent_category in recent:
        avoid_list.extend(category_kw_map.get(recent_category, []))

    return _RandomTopicPlan(
        category=forced_category,
        voice=forced_voice,
        voice_rule=voices[forced_voice],
        format=forced_format,
        opener=forced_opener,
        twist=forced_twist,
        must_keywords=must_keywords,
        avoid_keywords=", ".join(list(set(avoid_list))[:15]),
    )


def _log_random_plan(now: datetime, plan: _RandomTopicPlan) -> None:
    logger.info(
        "🎲 Topic: '%s', Voice: '%s', Format: '%s', Opener: '%s', Twist: '%s'",
        plan.category,
        plan.voice,
        plan.format,
        plan.opener[:80],
        plan.twist[:80],
    )
    dump_llm_draft(
        "random_wisdom_meta",
        json.dumps(
            {
                "ts": now.isoformat(timespec="seconds"),
                "forced_category": plan.category,
                "forced_voice": plan.voice,
                "forced_format": plan.format,
                "forced_opener": plan.opener,
                "forced_twist": plan.twist,
                "must_keywords": plan.must_keywords,
            },
            ensure_ascii=False,
        ),
    )


def _build_random_topic_messages(plan: _RandomTopicPlan) -> Optional[List[Dict[str, str]]]:
    system_prompt = load_prompt("random_topic_system")
    user_prompt = load_prompt(
        "random_topic_user",
        voice=plan.voice,
        voice_rule=plan.voice_rule,
        category=plan.category,
        format=plan.format,
        opener=plan.opener or "(없음)",
        twist=plan.twist or "(없음)",
        must_keywords=", ".join(plan.must_keywords) if plan.must_keywords else "(없음, 카테고리에 맞춰 자유롭게 창작)",
        avoid_keywords=plan.avoid_keywords if plan.avoid_keywords else "(없음)",
    )
    if not system_prompt or not user_prompt:
        logger.warning("Random topic prompt missing. Skip sending random message.")
        return None
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _build_random_title_messages(plan: _RandomTopicPlan, body: str) -> Optional[List[Dict[str, str]]]:
    system_prompt = load_prompt("random_topic_title_system")
    user_prompt = load_prompt(
        "random_topic_title_user",
        voice=plan.voice,
        category=plan.category,
        opener=plan.opener or "(없음)",
        twist=plan.twist or "(없음)",
        body=body,
    )
    if not system_prompt or not user_prompt:
        return None
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def _finalize_random_message(raw: str, attempt_no: int) -> str:
    korean_ratio = get_korean_ratio(raw)
    has_non_ko_cjk = _has_non_korean_cjk_chars(raw)
    has_replacement = _has_replacement_char(raw)
    final_text = raw
    if korean_ratio < 0.7 or has_non_ko_cjk or has_replacement:
        logger.info(
            "✂️ Attempt %s: Refining (ratio=%.2f, non_ko_cjk=%s, replacement_char=%s)...",
            attempt_no,
            korean_ratio,
            has_non_ko_cjk,
            has_replacement,
        )
        final_text = await refine_draft_with_light_llm_async(
            prompt_key="refine_random_wisdom",
            draft=raw,
            temperature=0.0,
            dump_tag="random_wisdom_refined",
        )
    return _postprocess_llm_text(final_text)


def _prepare_random_draft(raw: str) -> str:
    draft = raw or ""
    dump_llm_draft("random_wisdom_draft", draft)
    return draft


def _postprocess_random_title(raw: str) -> str:
    text = _postprocess_llm_text(raw or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    title = _RE_RANDOM_TITLE_PREFIX.sub("", lines[0]).strip()
    title = title.strip("\"'` ")
    title = _RE_WS.sub(" ", title)
    return title[:32].strip()


def _validate_random_title(title: str) -> Tuple[bool, str]:
    if not title:
        return False, "빈 제목"
    if len(title) < 4:
        return False, "제목이 너무 짧음"
    if len(title) > 28:
        return False, "제목이 너무 김"
    if any(ch in title for ch in "<>[]{}"):
        return False, "제목에 금지 문자 포함"
    if _has_non_korean_meta_output(title):
        return False, "제목에 메타 문장 포함"
    return True, ""


async def _generate_random_title_async(
    plan: _RandomTopicPlan,
    body: str,
    *,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    messages = _build_random_title_messages(plan, body)
    if not messages:
        return None

    options = _resolve_llm_options(llm_kwargs, default_max_tokens=48, default_temperature=0.75)
    try:
        raw = await generate_with_main_llm_async(
            messages,
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            stop=_build_stop_tokens(extra=["\n", "\n\n"]),
            enable_thinking=False,
            model=model,
            **options.extra_kwargs,
        )
    except Exception as exc:
        logger.warning("Random title generation failed: %s", exc)
        return None

    dump_llm_draft("random_wisdom_title_draft", raw or "")
    title = _postprocess_random_title(raw or "")
    ok, reason = _validate_random_title(title)
    if not ok:
        logger.warning("Random title rejected: %s. raw=%r", reason, raw)
        return None
    return title


def _validate_random_message(final_text: str, plan: _RandomTopicPlan) -> Tuple[bool, str]:
    if not final_text:
        return False, "정제 후 응답이 비어 있음"
    if not has_category_anchor(final_text, plan.category):
        return False, "카테고리 핵심 키워드 미포함"

    final_ratio = get_korean_ratio(final_text)
    if final_ratio < 0.8:
        return False, f"한국어 비율 {final_ratio:.2f} (< 0.80)"
    if _has_non_korean_cjk_chars(final_text):
        return False, "한글 외 CJK 문자 포함"
    if _has_replacement_char(final_text):
        return False, "깨진 문자(U+FFFD) 포함"
    return True, ""


async def _generate_random_message_payload_async(
    now: datetime,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[_RandomMessagePayload]:
    _hourly_reset_llm_context(now)

    plan = _pick_random_topic_plan()
    _log_random_plan(now, plan)

    messages = _build_random_topic_messages(plan)
    if not messages:
        return None

    options = _resolve_llm_options(llm_kwargs, default_max_tokens=512, default_temperature=0.85)
    failure_reasons: List[str] = []

    for attempt in range(2):
        attempt_no = attempt + 1
        logger.info("Generating random wisdom (Attempt %s/2)...", attempt_no)
        try:
            raw = await generate_with_main_llm_async(
                messages,
                max_tokens=options.max_tokens,
                temperature=options.temperature,
                enable_thinking=options.enable_thinking,
                model=model,
                **options.extra_kwargs,
            )
        except Exception as exc:
            reason = f"{attempt_no}회차: LLM 예외 ({_compact_reason(str(exc))})"
            failure_reasons.append(reason)
            logger.warning("Random wisdom generation failed (Attempt %s/2): %s", attempt_no, exc)
            continue

        draft = _prepare_random_draft(raw)
        if not draft.strip():
            failure_reasons.append(f"{attempt_no}회차: 응답이 비어 있음")
            continue

        text_length = len(draft.strip())
        if not (100 <= text_length <= 600):
            failure_reasons.append(f"{attempt_no}회차: 길이 {text_length}자 (허용 100~600자)")
            continue

        final_text = await _finalize_random_message(draft, attempt_no)
        ok, reason = _validate_random_message(final_text, plan)
        if not ok:
            failure_reasons.append(f"{attempt_no}회차: {reason}")
            continue

        title = await _generate_random_title_async(plan, final_text, model=model, **llm_kwargs)
        if not title:
            title = _default_random_title(now)

        save_recent_category(plan.category)
        save_last_random_topic_sent_at(now)
        logger.info("✅ Random wisdom success (Attempt %s/2)", attempt_no)
        return _RandomMessagePayload(title=title, body=final_text)

    if failure_reasons:
        logger.error(
            "Random wisdom failed after 2 attempts. category=%s, reasons=%s",
            plan.category,
            failure_reasons,
        )
    return None


async def _generate_random_message_async(
    now: datetime,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    payload = await _generate_random_message_payload_async(now, model=model, **llm_kwargs)
    return payload.body if payload else None


async def _generate_alarm_summary_async(
    items: List[dict],
    prompt_content: str,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    stop = _build_stop_tokens(extra=["\n\n\n", "...", "aaaa", "----"])
    options = _resolve_llm_options(llm_kwargs, default_max_tokens=512, default_temperature=0.05)
    extra_guard = (
        "\n\n[추가 규칙]\n"
        "- 'N건'만 나열하지 말고, 각 항목에서 최소 1개의 구체 단서(금액/날짜/상태/키워드/발신자/앱)를 포함해.\n"
        "- 알림에 없는 사실을 만들어내지 마.\n"
    )

    for attempt in range(2):
        attempt_no = attempt + 1
        logger.info("Generating alarm summary (Attempt %s/2)...", attempt_no)
        content = prompt_content if attempt_no == 1 else (prompt_content + extra_guard)
        raw = await generate_with_main_llm_async(
            [{"role": "user", "content": content}],
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            stop=stop,
            enable_thinking=options.enable_thinking,
            model=model,
            **options.extra_kwargs,
        )
        dump_llm_draft("alarm_summary_draft", raw)

        cleaned = sanitize_llm_output(items, raw or "")
        cleaned = _postprocess_llm_text(cleaned)
        ok, reason = _validate_alarm_summary(cleaned, items)
        if ok:
            return cleaned
        logger.warning(
            "Alarm summary rejected (Attempt %s/2): %s. text=%r",
            attempt_no,
            reason,
            cleaned,
        )

    return None


async def summarize_with_llm(items: List[dict], model: Optional[str] = None, **llm_kwargs) -> Optional[str]:
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        if not items:
            return None
        notification_list = _build_notification_list(items)
        return "\n".join(notification_list) if notification_list else None

    if not items:
        now = datetime.now()
        if not _should_send_random_topic(now):
            return None
        return await _generate_random_message_async(now, model=model, **llm_kwargs)

    notification_list = _build_notification_list(items)
    if not notification_list:
        return None

    notifications_str = "\n".join(notification_list)
    prompt_content = load_prompt("alarm_summary", notifications=notifications_str) or f"알림 요약:\n{notifications_str}"
    return await _generate_alarm_summary_async(items, prompt_content, model=model, **llm_kwargs)


async def generate_random_message_payload(
    now: Optional[datetime] = None,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[Dict[str, str]]:
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        return None

    base_now = now or datetime.now()
    if not _should_send_random_topic(base_now):
        return None

    payload = await _generate_random_message_payload_async(base_now, model=model, **llm_kwargs)
    if not payload:
        return None
    return {"title": payload.title, "body": payload.body}


async def summarize_expenses_with_llm(expenses: List[dict]) -> str:
    if not expenses:
        return ""

    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        return ""

    expense_lines = [f"- {expense['merchant']}: {abs(expense['amount']):,.0f}원 ({expense['category']})" for expense in expenses]
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
    return (result or "").strip()


__all__ = [
    "generate_random_message_payload",
    "summarize_with_llm",
    "summarize_expenses_with_llm",
]
