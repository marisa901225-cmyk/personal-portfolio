"""
Telegram Webhook Router - 텔레그램 봇 웹훅 엔드포인트
명령어와 자연어 질의를 적절한 핸들러로 라우팅
"""
import os
import logging

from fastapi import APIRouter, Request, HTTPException

from ..core.db import SessionLocal
from ..integrations.telegram import send_telegram_message
from .handlers.model_handler import handle_model_command
from .handlers.spam_handler import handle_spam_command
from .handlers.query_handler import handle_query, reset_session, classify_query

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

# 환경변수에서 시크릿 토큰과 허용된 채팅 ID 로드
WEBHOOK_SECRET = os.getenv("X_TELEGRAM_BOT_API_SECRET_TOKEN") or os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """텔레그램 업데이트 수신 웹훅"""
    
    # 1. Secret Token 검증
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if WEBHOOK_SECRET and secret_header != WEBHOOK_SECRET:
        logger.warning("Invalid webhook secret token (len=%s)", len(secret_header) if secret_header else 0)
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    # 2. 업데이트 파싱
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    message = update.get("message")
    if not message:
        return {"ok": True}
    
    # 3. Chat ID 검증 (본인만 허용)
    chat_id = str(message.get("chat", {}).get("id", ""))
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        logger.warning(f"Unauthorized chat_id: {chat_id}")
        return {"ok": True}
    
    # 4. 텍스트 추출 및 유효성 검사
    text = message.get("text", "").strip()
    if not text:
        return {"ok": True}
    
    # 5. 명령어 처리 (/)와 자연어 처리 흐름 분리
    if text.startswith("/"):
        await _handle_command(text, chat_id)
    else:
        # 자연어 처리
        logger.info("Natural language query received (len=%s)", len(text))
        try:
            await handle_query(text, chat_id)
        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            await send_telegram_message("답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
    
    return {"ok": True}


async def _handle_command(text: str, chat_id: str):
    """슬래시 명령어 처리"""
    parts = text[1:].split(maxsplit=1)
    cmd = parts[0] if len(parts) > 0 else ""
    arg = parts[1] if len(parts) > 1 else ""
    
    # /spam 접두사 지원 (하이브리드)
    if cmd == "spam":
        parts = arg.split(maxsplit=1)
        cmd = parts[0] if len(parts) > 0 else ""
        arg = parts[1] if len(parts) > 1 else ""
    
    # 지원하는 명령어 리스트
    SUPPORTED_CMDS = ["add", "del", "list", "on", "off", "help", "model", "reset", "report"]
    if cmd not in SUPPORTED_CMDS:
        return
    
    # 명령어별 처리
    response_text = ""
    
    if cmd == "report":
        from ..services.reporting.template import build_telegram_steam_trend_message
        response_text = build_telegram_steam_trend_message(arg)
        await send_telegram_message(response_text)
        return
    
    if cmd == "model":
        model_parts = arg.split(maxsplit=1)
        response_text = await handle_model_command(model_parts)
    elif cmd == "reset":
        reset_session(chat_id)
        response_text = "✅ 대화 내용이 초기화되었습니다."
    else:
        db = SessionLocal()
        try:
            response_text = await handle_spam_command(cmd, arg, db)
            
            # 규칙 변경 시 AI 모델 재학습 트리거
            if cmd in ["add", "del", "on", "off"] and any(icon in response_text for icon in ["✅", "🗑️", "⏸️", "▶️"]):
                from ..services.spam_trainer import train_spam_model
                if train_spam_model():
                    response_text += "\n� <i>AI 모델이 최신 규칙으로 재학습되었습니다.</i>"
        finally:
            db.close()
    
    if response_text:
        await send_telegram_message(response_text)
