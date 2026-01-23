# backend/services/alarm/fallback_logic.py
"""LLM 실패 시 폴백 메시지 생성 로직"""
import random
import re
from typing import List

from .random_categories import get_category_keywords
from .sanitizer import infer_source


# LLM 폴백 구분용 태그
FALLBACK_TAG = "[fallback]"


def mark_fallback(text: str) -> str:
    """폴백 메시지임을 표시"""
    if not text:
        return FALLBACK_TAG
    if text.lstrip().startswith(FALLBACK_TAG):
        return text
    return f"{FALLBACK_TAG}\n{text}"


def build_random_topic_fallback(category: str) -> str:
    """랜덤 메시지 생성 실패 시 카테고리 기반 폴백 메시지 생성"""
    category_keywords = get_category_keywords()
    keywords = list(category_keywords.get(category) or [])
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

    message = (
        f"{opener} {category} 잡학 한 토막! "
        f"{k1} 얘기만 하다 보면 {k2}가 슬쩍 튀어나오는데, 그 순간이 은근히 짜릿하다더라요. "
        f"다음에 {k1} 떠오르면 '아 그거!' 하고 피식 웃어봐요, {closer}"
    ).strip()
    return mark_fallback(message)


def build_alarm_summary_fallback(items: List[dict]) -> str:
    """
    LLM 요약 실패 시 입력 알림을 그대로(마스킹 유지) bullet로 반환
    - 창작 금지
    - 너무 길어지지 않도록 상위 N개만 노출
    """
    max_items = 6
    out: List[str] = []
    used = 0
    for it in items:
        if used >= max_items:
            break
        source = infer_source(it)
        title = (it.get("app_title") or "").strip()
        conv = (it.get("conversation") or "").strip()
        text = (it.get("text") or "").strip()
        parts = [p for p in (title, conv, text) if p]
        if not parts:
            continue
        out.append(f"- [{source}] " + " / ".join(parts))
        used += 1
    remaining = max(0, len(items) - used)
    if remaining > 0:
        out.append(f"- (외 {remaining}건)")
    return "\n".join(out).strip()

