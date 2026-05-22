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
        "memo": "사용자의 메모를 바탕으로 필요한 내용을 정리하고, 바로 메모장에 붙일 수 있게 간결하게 답해라.",
        "ask": "사용자의 질문에 답하되, 메모 내용이 있으면 그 내용을 우선 근거로 삼아라.",
        "rewrite": "사용자의 메모를 보존하면서 더 명확하고 쓰기 좋은 형태로 다듬어라.",
    }
    system = (
        "너는 개인 메모장 안에 붙어 있는 한국어 AI 보조 도구다. "
        "과장하지 말고, 짧고 실용적으로 답해라. "
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
