from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, List, Tuple

from .alarm_keywords import COUNT_ONLY_EXCEPTION_KEYWORDS

logger = logging.getLogger(__name__)

_RE_TOKEN = re.compile(r"[가-힣A-Za-z0-9_*]+")
_RE_BULLET_PREFIX = re.compile(r"^[-•*]\s*")
_RE_COUNT_ONLY = re.compile(r"\b\d+\s*건\b")
_RE_ENGLISH_REASONING = re.compile(
    r"(looking at|the title is|okay[, ]|let's|first[, ]|since there's|so the summary should|i need to)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _AlarmSummaryDeps:
    build_stop_tokens: Any
    resolve_llm_options: Any
    generate_with_main_llm_async: Any
    dump_llm_draft: Any
    sanitize_llm_output: Any
    postprocess_llm_text: Any
    get_korean_ratio: Any


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


def _has_non_korean_meta_output(text: str, get_korean_ratio) -> bool:
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


def _has_invalid_bullet_format(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    return any(not line.startswith(("-", "•", "*")) for line in lines)


def _validate_alarm_summary(text: str, items: List[dict], deps: _AlarmSummaryDeps) -> Tuple[bool, str]:
    if _is_weak_summary(text):
        return False, "요약이 너무 짧거나 무의미함"
    if _has_invalid_bullet_format(text):
        return False, "출력 형식 위반(불릿 형식 아님)"
    if _has_non_korean_meta_output(text, deps.get_korean_ratio):
        return False, "영어 메타/사고문장 포함"
    if _looks_like_count_only_summary(text, items):
        return False, "단순 카운트(몇 건) 나열로 보임"
    return True, ""


async def _generate_alarm_summary_async(
    items: List[dict],
    prompt_content: str,
    *,
    deps: _AlarmSummaryDeps,
    model: str | None = None,
    **llm_kwargs,
) -> str | None:
    # `...` can legitimately appear in nicknames/titles (e.g. truncated live titles),
    # so treating it as a hard stop can cut summaries mid-sentence.
    stop = deps.build_stop_tokens(extra=["\n\n\n", "aaaa", "----"])
    options = deps.resolve_llm_options(llm_kwargs, default_max_tokens=512, default_temperature=0.05)
    extra_guard = (
        "\n\n[추가 규칙]\n"
        "- 'N건'만 나열하지 말고, 각 항목에서 최소 1개의 구체 단서(금액/날짜/상태/키워드/발신자/앱)를 포함해.\n"
        "- 알림에 없는 사실을 만들어내지 마.\n"
    )

    for attempt in range(2):
        attempt_no = attempt + 1
        logger.info("Generating alarm summary (Attempt %s/2)...", attempt_no)
        content = prompt_content if attempt_no == 1 else (prompt_content + extra_guard)
        raw = await deps.generate_with_main_llm_async(
            [{"role": "user", "content": content}],
            max_tokens=options.max_tokens,
            temperature=options.temperature,
            stop=stop,
            enable_thinking=options.enable_thinking,
            model=model,
            **options.extra_kwargs,
        )
        deps.dump_llm_draft("alarm_summary_draft", raw)

        cleaned = deps.sanitize_llm_output(items, raw or "")
        cleaned = deps.postprocess_llm_text(cleaned)
        ok, reason = _validate_alarm_summary(cleaned, items, deps)
        if ok:
            return cleaned
        logger.warning(
            "Alarm summary rejected (Attempt %s/2): %s. text=%r",
            attempt_no,
            reason,
            cleaned,
        )

    return None
