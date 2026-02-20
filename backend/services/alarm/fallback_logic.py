from typing import List
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

