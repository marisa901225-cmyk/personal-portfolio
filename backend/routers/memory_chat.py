from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.rate_limit import rate_limit
from ..services.memory_service import search_memories
from ..services import memory_chat_service as service

router = APIRouter(prefix="/api/memories", tags=["Memories"], dependencies=[Depends(verify_api_token)])
logger = logging.getLogger(__name__)

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    max_tokens: int = 1024
    session_id: Optional[str] = None

@router.post("/chat")
def memory_chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit(limit=20, window_sec=60, key_prefix="memory_chat")),
):
    """AI 장기기억 대화방 엔드포인트"""
    try:
        session_id = req.session_id or "default"
        # 최신 메시지 기반으로 관련 기억 검색
        last_user_msg = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        
        try:
            memories = search_memories(db, user_id=1, query=last_user_msg, limit=10)
        except Exception:
            logger.exception("Memory search failed; continuing without memories")
            memories = []

        memories_text = ""
        if memories:
            cat_map = {}
            for m in memories:
                if m.category not in cat_map:
                    cat_map[m.category] = []
                cat_map[m.category].append(m.content)

            lines = []
            for cat, m_list in cat_map.items():
                lines.append(f"• {cat.upper()}:")
                for content in m_list:
                    lines.append(f"  - {content}")
            memories_text = "\n".join(lines)

        # API 메시지 형식으로 변환
        api_messages = [m.model_dump() for m in req.messages]
        summary_text, trimmed_messages = service.prepare_chat_context(session_id, api_messages)

        db_context = ""
        if service.needs_db_context(last_user_msg):
            db_context = service.build_db_context(last_user_msg)

        return StreamingResponse(
            service.chat_stream_generator(
                trimmed_messages,
                memories_text,
                summary_text,
                db_context,
                req.model,
                req.max_tokens,
            ),
            media_type="text/plain; charset=utf-8",
        )
    except Exception:
        logger.exception("Memory chat failed")

        def fallback():
            yield service.DEFAULT_FALLBACK_MESSAGE

        return StreamingResponse(
            fallback(),
            media_type="text/plain; charset=utf-8",
        )
