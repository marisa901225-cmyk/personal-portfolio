from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..core.auth import verify_api_token
from ..core.rate_limit import rate_limit
from ..services.llm_service import LLMService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/ai-chat",
    tags=["AI Chat"],
    dependencies=[
        Depends(verify_api_token),
        Depends(rate_limit(limit=20, window_sec=60, key_prefix="ai_chat")),
    ],
)


class AiChatMessageRequest(BaseModel):
    memo: str = Field(default="", max_length=30000)
    instruction: str = Field(..., min_length=1, max_length=4000)
    max_tokens: int = Field(default=1536, ge=64, le=4096)
    temperature: float = Field(default=0.4, ge=0.0, le=1.5)
    mode: Literal["memo", "ask", "rewrite"] = "memo"


class AiChatMessageResponse(BaseModel):
    answer: str
    route: str | None = None
    used_paid: bool = False


def _build_messages(payload: AiChatMessageRequest) -> list[dict[str, str]]:
    mode_hints = {
        "memo": "메모를 항목별로 정리하되 원문의 숫자, 단위, 약어를 절대 바꾸지 마라.",
        "ask": "질문에 답하되 메모 내용이 있으면 그 내용을 우선 근거로 삼고, 모호한 값은 확인 필요로 표시해라.",
        "rewrite": "원문의 의미와 표기를 보존하면서 문장만 더 읽기 좋게 다듬어라.",
    }
    system = (
        "당신은 LPH-1 메모장 대용으로 붙어 있는 한국어 AI 보조 도구입니다.\n"
        "목표는 메모 정리, 초안 다듬기, 짧은 질문 답변입니다.\n\n"
        "## 메모 정리 규칙\n"
        "- 원문에 있는 숫자, 음수, 단위, 약어, 대소문자, 기호를 보존하세요.\n"
        "- `mg`, `Elb`, `LPH-1`처럼 의미가 불명확한 약어를 임의로 풀거나 교정하지 마세요.\n"
        "- `-50`, `-32` 같은 값은 부호를 유지하세요.\n"
        "- 줄바꿈이 없는 짧은 메모는 왼쪽부터 읽어 `라벨 값` 형태로 정리하세요.\n"
        "- 마지막 숫자도 버리지 마세요. 예: `7 Elb 8`은 `7 Elb: 8`처럼 보존하세요.\n"
        "- 정리 가능한 항목 수가 보이면 `항목 N개`처럼 짧게 요약하세요.\n"
        "- 깨진 메모처럼 보여도 추측해서 새 정보를 만들지 말고 `확인 필요`로 표시하세요.\n"
        "- 최종 답변은 메모장에 바로 붙일 수 있게 짧은 목록이나 표로 작성하세요.\n"
        "- 사용자가 계산, 비교, 분석을 요청한 경우에만 `<reason>` 태그 안에 간단한 검토 과정을 먼저 쓰고, "
        "태그 밖에 최종 답변을 간결하게 작성하세요.\n\n"
        "## Few-shot 예시\n"
        "사용자 메모:\n"
        "LPH-1 메모장 대용 mg -50 1 mg -32 7 Elb 8\n"
        "요청: 정리해줘\n"
        "답변:\n"
        "LPH-1 메모\n"
        "항목 3개\n"
        "- mg: -50\n"
        "- 1 mg: -32\n"
        "- 7 Elb: 8\n\n"
        "사용자 메모:\n"
        "사과 3개 200원, 7개면?\n"
        "요청: 계산해줘\n"
        "답변:\n"
        "<reason>\n"
        "1개당 가격은 200/3원입니다. 7개 가격은 200/3*7원입니다.\n"
        "</reason>\n"
        "약 467원입니다.\n\n"
        f"{mode_hints[payload.mode]}"
    )
    user = f"메모:\n{payload.memo.strip() or '(비어 있음)'}\n\n요청:\n{payload.instruction.strip()}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


@router.post("/messages", response_model=AiChatMessageResponse)
async def create_ai_chat_message(payload: AiChatMessageRequest) -> AiChatMessageResponse:
    llm = LLMService.get_instance()
    try:
        answer = await run_in_threadpool(
            llm.generate_chat,
            _build_messages(payload),
            max_tokens=payload.max_tokens,
            temperature=payload.temperature,
            top_p=0.9,
            allow_paid_fallback=True,
        )
    except Exception as exc:
        logger.exception("AI memo request failed")
        raise HTTPException(status_code=502, detail="AI server request failed") from exc

    if not answer.strip():
        raise HTTPException(
            status_code=502,
            detail=llm.get_last_error() or "AI server returned an empty response",
        )

    return AiChatMessageResponse(
        answer=answer.strip(),
        route=llm.last_route(),
        used_paid=llm.last_used_paid(),
    )
