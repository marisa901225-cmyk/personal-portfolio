from __future__ import annotations

import re
import time
from dataclasses import dataclass

from backend.core.config import settings
from backend.services.llm.service import LLMService


MODEL = "deepseek/deepseek-v4-flash"
BASE_URL = "https://openrouter.ai/api/v1"

INNER_OS_MARKER = (
    "\n\n〖角色沉浸要求〗在你的思考过程（<think>标签内）中，请遵守以下规则：\n"
    "1. 请以角色第一人称进行内心独白，用括号包裹内心活动，例如\"（心想：……）\"或\"(内心OS：……)\"\n"
    "2. 用第一人称描写角色的内心感受，例如\"我心想\"\"我觉得\"\"我暗自\"等\n"
    "3. 思考内容应沉浸在角色中，通过内心独白分析剧情和规划回复"
)

NO_INNER_OS_MARKER = (
    "\n\n〖思维模式要求〗在你的思考过程（<think>标签内）中，请遵守以下规则：\n"
    "1. 禁止使用圆括号包裹内心独白，例如\"（心想：……）\"或\"(内心OS：……)\"，所有分析内容直接陈述即可\n"
    "2. 禁止以角色第一人称描写内心活动，例如\"我心想\"\"我觉得\"\"我暗自\"等，请用分析性语言替代\n"
    "3. 思考内容应聚焦于剧情走向分析和回复内容规划，不要在思考中进行角色扮演式的内心戏表演"
)


@dataclass(frozen=True)
class Trial:
    label: str
    suffix: str


def _strip_think(text: str) -> tuple[str, int]:
    spans = re.findall(r"<think>.*?</think>", text or "", flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<think>.*?</think>", "[think omitted]", text or "", flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip(), sum(len(span) for span in spans)


def _call(label: str, suffix: str) -> None:
    prompt = (
        "너는 비 오는 심야 편의점의 조용한 알바생 캐릭터다. "
        "손님이 계산대 앞에서 '오늘 하루가 너무 길었어요'라고 말한다. "
        "한국어로만, 180자 안팎으로, 행동 묘사 1문장과 대사 1문장으로 답해라. "
        "사고과정이나 <think>는 출력하지 마라."
    )
    service = LLMService.get_instance()
    started = time.time()
    response = service.generate_paid_chat(
        messages=[{"role": "user", "content": prompt + suffix}],
        model=MODEL,
        api_key=settings.open_api_key or settings.ai_report_api_key,
        base_url=BASE_URL,
        max_tokens=260,
        temperature=0.7,
        top_p=0.9,
    )
    elapsed = time.time() - started
    cleaned, think_chars = _strip_think(response)
    print(f"\n=== {label} ===")
    print(f"elapsed={elapsed:.2f}s chars={len(response)} think_chars={think_chars}")
    print(cleaned or f"[empty] last_error={service.get_last_error()}")


def main() -> None:
    if not (settings.open_api_key or settings.ai_report_api_key):
        raise SystemExit("OPEN_API_KEY or AI_REPORT_API_KEY is missing")

    trials = [
        Trial("default", ""),
        Trial("inner_os_marker", INNER_OS_MARKER),
        Trial("no_inner_os_marker", NO_INNER_OS_MARKER),
    ]
    for trial in trials:
        _call(trial.label, trial.suffix)


if __name__ == "__main__":
    main()
