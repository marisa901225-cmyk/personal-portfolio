from __future__ import annotations

import re
import time
from argparse import ArgumentParser
from dataclasses import dataclass

from backend.core.config import settings
from backend.services.llm.service import LLMService


DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
BASE_URL = "https://openrouter.ai/api/v1"

INNER_OS_MARKER = (
    "\n\n〖角色沉浸要求〗在你的思考过程（<think>标签内）中，请遵守以下规则：\n"
    "1. 请以角色第一人称进行内心独白，用括号包裹内心活动，例如\"（心想：……）\"或\"(内心OS：……)\"\n"
    "2. 用第一人称描写角色的内心感受，例如\"我心想\"\"我觉得\"\"我暗自\"等\n"
    "3. 思考内容应沉浸在角色中，通过内心独白分析剧情和规划回复"
)


@dataclass(frozen=True)
class Persona:
    label: str
    description: str


PERSONAS = [
    Persona("warm", "다정하고 생활감 있는 20대 청년. 말투는 낮고 부드럽고, 상대를 부담스럽게 위로하지 않는다."),
    Persona("tsundere", "까칠하지만 속정 깊은 20대 청년. 툴툴거리지만 행동으로 챙긴다."),
    Persona("playful", "장난기 많고 눈치 빠른 20대 청년. 분위기를 가볍게 풀되 진심은 숨기지 않는다."),
    Persona("quiet", "말수가 적고 무뚝뚝한 20대 청년. 짧은 말과 작은 행동으로 마음을 보인다."),
    Persona("artist", "감성적인 밴드 보컬 같은 20대 청년. 비유가 있지만 과장하지 않고 담백하다."),
    Persona("rational", "이성적이고 정돈된 20대 청년. 감정을 무시하지 않고 현실적인 선택지를 준다."),
]


def _strip_think(text: str) -> tuple[str, int]:
    spans = re.findall(r"<think>.*?</think>", text or "", flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<think>.*?</think>", "[think omitted]", text or "", flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip(), sum(len(span) for span in spans)


def _call(persona: Persona, *, model: str) -> None:
    prompt = (
        f"너는 다음 성격의 한국인 20대 청년 캐릭터다: {persona.description}\n"
        "상황: 비 오는 밤, 오래 알고 지낸 친구가 편의점 앞에서 우산도 없이 서 있다. "
        "친구가 '나 오늘 진짜 망한 것 같아'라고 말한다.\n"
        "요구: 한국어로만 답해라. 120자 안팎. 행동 묘사 1문장 + 대사 1문장. "
        "설명문, 분석문, 사고과정, <think>는 출력하지 마라."
    )
    service = LLMService.get_instance()
    started = time.time()
    response = service.generate_paid_chat(
        messages=[{"role": "user", "content": prompt + INNER_OS_MARKER}],
        model=model,
        api_key=settings.open_api_key or settings.ai_report_api_key,
        base_url=BASE_URL,
        max_tokens=220,
        temperature=0.85,
        top_p=0.92,
    )
    elapsed = time.time() - started
    cleaned, think_chars = _strip_think(response)
    print(f"\n=== {persona.label} ===")
    print(f"elapsed={elapsed:.2f}s chars={len(response)} think_chars={think_chars}")
    print(cleaned or f"[empty] last_error={service.get_last_error()}")


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    if not (settings.open_api_key or settings.ai_report_api_key):
        raise SystemExit("OPEN_API_KEY or AI_REPORT_API_KEY is missing")
    print(f"model={args.model}")
    for persona in PERSONAS:
        _call(persona, model=args.model)


if __name__ == "__main__":
    main()
