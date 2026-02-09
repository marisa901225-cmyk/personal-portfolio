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

    # ✅ 키워드 풀이 충분할 때와 없을 때를 구분하여 메시지 생성
    if len(pool) >= 2:
        picked = random.sample(pool, k=2)
        k1, k2 = picked[0], picked[1]
        body = f"{k1} 얘기만 하다 보면 {k2}가 슬쩍 튀어나오는데, 그 순간이 은근히 짜릿하다더라요. 다음에 {k1} 떠오르면 '아 그거!' 하고 피식 웃어봐요."
    else:
        # 키워드가 없거나 부족할 때 (LO 요청: 카테고리 중심)
        body = f"{category}에 대해 깊이 생각하다 보면 세상이 조금은 다르게 보일지도 몰라요. 때로는 정해진 내용보다 당신의 상상이 더 큰 정답일 수 있거든요."

    openers = ["툭 던지는", "쓱 꺼내는", "탁 치는", "살짝 과장한"]
    closers = ["아무튼 오늘은 여기까지!", "아무튼 그렇다더라!", "아무튼 다음에 또 툭!", "아무튼 뇌가 간질간질하죠?"]

    opener = random.choice(openers)
    closer = random.choice(closers)

    message = f"{opener} {category} 이야기 한 토막! {body} {closer}"
    return mark_fallback(message.strip())


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

