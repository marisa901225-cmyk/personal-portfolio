from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_RE_WS = re.compile(r"\s+")
_RE_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_RE_ENGLISH_REASONING = re.compile(
    r"(looking at|the title is|okay[, ]|let's|first[, ]|since there's|so the summary should|i need to)",
    re.IGNORECASE,
)
_RE_NON_KOREAN_CJK = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\u3040-\u30FF\u31F0-\u31FF]")
_RE_RANDOM_TITLE_PREFIX = re.compile(r"^\s*(title|제목)\s*:\s*", re.IGNORECASE)
_RE_EXPLANATORY_TAIL = re.compile(
    r"(^\s*(결론적으로|정리하면|한마디로|요컨대)\b)|"
    r"(바랍니다|좋겠습니다|해보세요|하시길|권합니다)|"
    r"(느낌이 들(?:었다|었습니다|겠다)|느껴집니다|남겨집니다|정리됩니다|정리된다)|"
    r"(셈이(?:다|니다|니))",
    re.IGNORECASE,
)
_REPLACEMENT_CHAR = "\ufffd"


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


@dataclass(frozen=True, slots=True)
class _RandomTopicDeps:
    get_all_categories: Any
    get_formats: Any
    get_openers: Any
    get_twists: Any
    get_voices: Any
    has_category_anchor: Any
    load_last_random_topic_sent_at: Any
    load_recent_categories: Any
    pick_keywords_for_constraints: Any
    save_last_random_topic_sent_at: Any
    save_recent_category: Any
    get_category_keywords: Any
    load_prompt: Any
    get_korean_ratio: Any
    dump_llm_draft: Any
    generate_with_main_llm_async: Any
    refine_draft_with_light_llm_async: Any
    resolve_llm_options: Any
    build_stop_tokens: Any
    postprocess_llm_text: Any
    compact_reason: Any
    hourly_reset_llm_context: Any
    random_module: Any


def _has_non_korean_meta_output(text: str, deps: _RandomTopicDeps) -> bool:
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
        if deps.get_korean_ratio(line) < 0.25:
            return True
    return False


def _has_non_korean_cjk_chars(text: str) -> bool:
    return bool(_RE_NON_KOREAN_CJK.search(text or ""))


def _has_replacement_char(text: str) -> bool:
    return _REPLACEMENT_CHAR in (text or "")


def _get_last_sentence(text: str) -> str:
    sentences = [part.strip() for part in _RE_SENTENCE_BOUNDARY.split(text or "") if part and part.strip()]
    if sentences:
        return sentences[-1]
    return (text or "").strip()


def _has_explanatory_tail(text: str) -> bool:
    last_sentence = _get_last_sentence(text)
    if not last_sentence:
        return False
    return bool(_RE_EXPLANATORY_TAIL.search(last_sentence))


def _default_random_title(now: datetime) -> str:
    titles = ["오늘의 브리핑", "읽을거리", "짧은 메모", "오늘의 한 조각", "가벼운 이야기", "생각 한 스푼"]
    return titles[(now.minute // 10) % len(titles)]


def _pick_random_topic_plan(deps: _RandomTopicDeps) -> _RandomTopicPlan:
    all_categories = deps.get_all_categories()
    formats = deps.get_formats()
    openers = deps.get_openers()
    twists = deps.get_twists()
    recent = [category.strip() for category in deps.load_recent_categories() if category and category.strip()]
    available_categories = [category for category in all_categories if category.strip() not in set(recent)] or all_categories

    voices = deps.get_voices()
    forced_voice = deps.random_module.choice(list(voices.keys()))
    forced_category = deps.random_module.choice(available_categories)
    forced_format = deps.random_module.choice(formats)
    forced_opener = deps.random_module.choice(openers) if openers else ""
    forced_twist = deps.random_module.choice(twists) if twists else ""

    must_keywords = deps.pick_keywords_for_constraints(forced_category, count=4)
    deps.random_module.shuffle(must_keywords)

    category_kw_map = deps.get_category_keywords()
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


def _log_random_plan(now: datetime, plan: _RandomTopicPlan, deps: _RandomTopicDeps) -> None:
    logger.info(
        "🎲 Topic: '%s', Voice: '%s', Format: '%s', Opener: '%s', Twist: '%s'",
        plan.category,
        plan.voice,
        plan.format,
        plan.opener[:80],
        plan.twist[:80],
    )
    deps.dump_llm_draft(
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


def _build_random_topic_messages(plan: _RandomTopicPlan, deps: _RandomTopicDeps) -> Optional[List[Dict[str, str]]]:
    system_prompt = deps.load_prompt("random_topic_system")
    user_prompt = deps.load_prompt(
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


def _load_paid_system_prompt(prompt_name: str, deps: _RandomTopicDeps) -> Optional[str]:
    prompt = deps.load_prompt(prompt_name)
    text = str(prompt or "").strip()
    return text or None


def _build_random_title_messages(
    plan: _RandomTopicPlan,
    body: str,
    deps: _RandomTopicDeps,
) -> Optional[List[Dict[str, str]]]:
    system_prompt = deps.load_prompt("random_topic_title_system")
    user_prompt = deps.load_prompt(
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


async def _finalize_random_message(raw: str, attempt_no: int, deps: _RandomTopicDeps) -> str:
    korean_ratio = deps.get_korean_ratio(raw)
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
        final_text = await deps.refine_draft_with_light_llm_async(
            prompt_key="refine_random_wisdom",
            draft=raw,
            temperature=0.0,
            dump_tag="random_wisdom_refined",
        )
    return deps.postprocess_llm_text(final_text)


def _prepare_random_draft(raw: str, deps: _RandomTopicDeps) -> str:
    draft = raw or ""
    deps.dump_llm_draft("random_wisdom_draft", draft)
    return draft


def _postprocess_random_title(raw: str, deps: _RandomTopicDeps) -> str:
    text = deps.postprocess_llm_text(raw or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    title = _RE_RANDOM_TITLE_PREFIX.sub("", lines[0]).strip()
    title = title.strip("\"'` ")
    title = _RE_WS.sub(" ", title)
    return title[:32].strip()


def _validate_random_title(title: str, deps: _RandomTopicDeps) -> Tuple[bool, str]:
    if not title:
        return False, "빈 제목"
    if len(title) < 4:
        return False, "제목이 너무 짧음"
    if len(title) > 28:
        return False, "제목이 너무 김"
    if any(ch in title for ch in "<>[]{}"):
        return False, "제목에 금지 문자 포함"
    if _has_non_korean_meta_output(title, deps):
        return False, "제목에 메타 문장 포함"
    return True, ""


async def _generate_random_title_async(
    plan: _RandomTopicPlan,
    body: str,
    *,
    deps: _RandomTopicDeps,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[str]:
    messages = _build_random_title_messages(plan, body, deps)
    if not messages:
        return None

    options = deps.resolve_llm_options(llm_kwargs, default_max_tokens=48, default_temperature=0.75)
    paid_system_prompt = _load_paid_system_prompt("random_topic_title_gpt5_paid_system", deps)
    try:
        raw = await deps.generate_with_main_llm_async(
            messages,
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            stop=deps.build_stop_tokens(extra=["\n", "\n\n"]),
            enable_thinking=False,
            reasoning_effort="none",
            paid_system_prompt=paid_system_prompt,
            model=model,
            **options.extra_kwargs,
        )
    except Exception as exc:
        logger.warning("Random title generation failed: %s", exc)
        return None

    deps.dump_llm_draft("random_wisdom_title_draft", raw or "")
    title = _postprocess_random_title(raw or "", deps)
    ok, reason = _validate_random_title(title, deps)
    if not ok:
        logger.warning("Random title rejected: %s. raw=%r", reason, raw)
        return None
    return title


def _validate_random_message(final_text: str, plan: _RandomTopicPlan, deps: _RandomTopicDeps) -> Tuple[bool, str]:
    if not final_text:
        return False, "정제 후 응답이 비어 있음"
    if not deps.has_category_anchor(final_text, plan.category):
        return False, "카테고리 핵심 키워드 미포함"
    if _has_explanatory_tail(final_text):
        return False, "마지막 문장이 설명/권유 꼬리로 끝남"

    final_ratio = deps.get_korean_ratio(final_text)
    if final_ratio < 0.8:
        return False, f"한국어 비율 {final_ratio:.2f} (< 0.80)"
    if _has_non_korean_cjk_chars(final_text):
        return False, "한글 외 CJK 문자 포함"
    if _has_replacement_char(final_text):
        return False, "깨진 문자(U+FFFD) 포함"
    return True, ""


async def _generate_random_message_payload_async(
    now: datetime,
    *,
    deps: _RandomTopicDeps,
    model: Optional[str] = None,
    **llm_kwargs,
) -> Optional[_RandomMessagePayload]:
    deps.hourly_reset_llm_context(now)

    plan = _pick_random_topic_plan(deps)
    _log_random_plan(now, plan, deps)

    messages = _build_random_topic_messages(plan, deps)
    if not messages:
        return None

    options = deps.resolve_llm_options(llm_kwargs, default_max_tokens=512, default_temperature=0.85)
    paid_system_prompt = _load_paid_system_prompt("random_topic_gpt5_paid_system", deps)
    failure_reasons: List[str] = []

    for attempt in range(2):
        attempt_no = attempt + 1
        logger.info("Generating random wisdom (Attempt %s/2)...", attempt_no)
        try:
            raw = await deps.generate_with_main_llm_async(
                messages,
                max_tokens=options.max_tokens,
                temperature=options.temperature,
                enable_thinking=options.enable_thinking,
                paid_system_prompt=paid_system_prompt,
                model=model,
                **options.extra_kwargs,
            )
        except Exception as exc:
            reason = f"{attempt_no}회차: LLM 예외 ({deps.compact_reason(str(exc))})"
            failure_reasons.append(reason)
            logger.warning("Random wisdom generation failed (Attempt %s/2): %s", attempt_no, exc)
            continue

        draft = _prepare_random_draft(raw, deps)
        if not draft.strip():
            failure_reasons.append(f"{attempt_no}회차: 응답이 비어 있음")
            continue

        text_length = len(draft.strip())
        if not (100 <= text_length <= 600):
            failure_reasons.append(f"{attempt_no}회차: 길이 {text_length}자 (허용 100~600자)")
            continue

        final_text = await _finalize_random_message(draft, attempt_no, deps)
        ok, reason = _validate_random_message(final_text, plan, deps)
        if not ok:
            failure_reasons.append(f"{attempt_no}회차: {reason}")
            continue

        title = await _generate_random_title_async(plan, final_text, deps=deps, model=model, **llm_kwargs)
        if not title:
            title = _default_random_title(now)

        deps.save_recent_category(plan.category)
        deps.save_last_random_topic_sent_at(now)
        logger.info("✅ Random wisdom success (Attempt %s/2)", attempt_no)
        return _RandomMessagePayload(title=title, body=final_text)

    if failure_reasons:
        logger.error(
            "Random wisdom failed after 2 attempts. category=%s, reasons=%s",
            plan.category,
            failure_reasons,
        )
    return None
