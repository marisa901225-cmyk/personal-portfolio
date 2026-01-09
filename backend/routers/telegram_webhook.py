"""
Telegram Webhook Router - 텔레그램 봇 명령어 처리
/spam add {pattern} - 스팸 규칙 추가
/spam del {id} - 스팸 규칙 삭제
/spam list - 스팸 규칙 목록
"""
import os
import logging
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..core.models import SpamRule
from ..integrations.telegram import send_telegram_message

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

# 환경변수에서 시크릿 토큰과 허용된 채팅 ID 로드
WEBHOOK_SECRET = os.getenv("X_TELEGRAM_BOT_API_SECRET_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALARM_TELEGRAM_CHAT_ID")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """텔레그램 업데이트 수신 웹훅"""
    
    # 1. Secret Token 검증
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if WEBHOOK_SECRET and secret_header != WEBHOOK_SECRET:
        logger.warning(f"Invalid webhook secret: {secret_header}")
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    # 2. 업데이트 파싱
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    message = update.get("message")
    if not message:
        return {"ok": True}  # 메시지가 아닌 업데이트는 무시
    
    # 3. Chat ID 검증 (본인만 허용)
    chat_id = str(message.get("chat", {}).get("id", ""))
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        logger.warning(f"Unauthorized chat_id: {chat_id}")
        return {"ok": True}  # 조용히 무시
    
    # 4. 텍스트 파싱 및 명령어 추출
    text = message.get("text", "").strip()
    
    # 명령어 처리 (/)
    if text.startswith("/"):
        # 예: "/add 키워드" -> cmd="add", arg="키워드"
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0] if len(parts) > 0 else ""
        arg = parts[1] if len(parts) > 1 else ""
        
        # /spam 접두사 지원 (하이브리드)
        if cmd == "spam":
            parts = arg.split(maxsplit=1)
            cmd = parts[0] if len(parts) > 0 else ""
            arg = parts[1] if len(parts) > 1 else ""
        
        # 지원하는 명령어 리스트
        SUPPORTED_CMDS = ["add", "del", "list", "on", "off", "help"]
        if cmd not in SUPPORTED_CMDS:
            return {"ok": True}
        
        db = SessionLocal()
        try:
            response_text = await handle_spam_command(cmd, arg, db)
            
            # 규칙 변경(add, del, on, off)이 있으면 AI 모델 재학습 트리거
            if cmd in ["add", "del", "on", "off"] and ("✅" in response_text or "🗑️" in response_text or "⏸️" in response_text or "▶️" in response_text):
                from ..services.spam_trainer import train_spam_model
                if train_spam_model():
                    response_text += "\n🔄 <i>AI 모델이 최신 규칙으로 재학습되었습니다.</i>"
            
            await send_telegram_message(response_text)
        finally:
            db.close()
    else:
        # 일반 텍스트: e스포츠 일정 RAG 처리
        if not text:
            return {"ok": True}
            
        logger.info(f"Natural language query received: {text}")
        db = SessionLocal()
        try:
            # 1. DuckDB를 이용한 관련 일정 검색 및 정제 (RAG - Retrieval & Refinement)
            from ..services.news_collector import NewsCollector
            context_text = NewsCollector.refine_schedules_with_duckdb(text)
            
            # 2. LLM에게 답변 생성 요청 (RAG - Generation)
            from ..services.llm_service import LLMService
            llm = LLMService.get_instance()
            if not llm.is_remote_ready():
                await send_telegram_message("LLM 원격 서버가 설정되지 않아 일정 답변을 생성할 수 없습니다.")
                return {"ok": True}
            
            prompt = f"""<start_of_turn>user
당신은 e스포츠 전문가이자 사용자의 개인 비서입니다. 
사용자의 질문과 아래 제공된 경기 일정 데이터를 바탕으로 친절하고 명확하게 답변해 주세요.

[제공된 경기 일정 데이터]
{context_text}

[사용자의 질문]
{text}

[답변 규칙]
- 한국어로 답변하세요.
- 데이터에 있는 내용을 기반으로 정확하게 안내하세요. 만약 데이터에 없는 내용이라면 모른다고 정직하게 말하세요.
- 친절하고 위트 있는 말투를 사용하세요.
- 일시 정보를 포함하여 경기 정보를 깔끔하게 정리해 주세요.

답변:<end_of_turn>
<start_of_turn>model
"""
            response_text = llm.generate_remote(prompt, max_tokens=1024)
            if not response_text:
                response_text = "죄송합니다. 답변을 생성하는 중에 문제가 발생했습니다. 😅"
            
            await send_telegram_message(response_text)
        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            await send_telegram_message("일정 검색 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
        finally:
            db.close()
    
    return {"ok": True}


async def handle_spam_command(cmd: str, arg: str, db: Session) -> str:
    """
    /add, /del, /list, /on, /off 명령어 처리
    """
    if cmd == "add" and arg:
        # 콤마로 구분하여 여러 개 동시 등록 지원 (예: /add 문피아, 이벤트)
        patterns = [p.strip() for p in arg.split(",") if p.strip()]
        added_ids = []
        for p in patterns:
            new_rule = SpamRule(
                rule_type="contains",
                pattern=p,
                category="general",
                note="텔레그램 추가",
                is_enabled=True,
                created_at=datetime.utcnow()
            )
            db.add(new_rule)
            db.commit()
            added_ids.append(f"#{new_rule.id}")
        
        patterns_str = ", ".join([f"<code>{p}</code>" for p in patterns])
        return f"✅ 스팸 규칙 {len(patterns)}개 추가됨: {patterns_str} ({', '.join(added_ids)})"
    
    elif cmd == "del" and arg:
        try:
            rule_id = int(arg)
        except ValueError:
            return "❌ ID는 숫자여야 합니다 (예: /del 15)"
        
        rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
        if not rule:
            return f"❌ 규칙 #{rule_id}를 찾을 수 없습니다"
        
        pattern = rule.pattern
        db.delete(rule)
        db.commit()
        return f"🗑️ 규칙 #{rule_id} 삭제됨: <code>{pattern}</code>"
    
    elif cmd == "list":
        # 현재는 모든 규칙을 보여주되 상태 표시
        rules = db.query(SpamRule).order_by(SpamRule.id.desc()).limit(30).all()
        if not rules:
            return "📋 등록된 스팸 규칙이 없습니다"
        
        lines = ["<b>📋 스팸 규칙 목록 (최신 30개)</b>"]
        for r in rules:
            status_icon = "🟢" if r.is_enabled else "🔴"
            # 긴 패턴은 자르기
            disp_pattern = (r.pattern[:20] + "..") if len(r.pattern) > 20 else r.pattern
            lines.append(f"{status_icon} #{r.id} [<code>{disp_pattern}</code>]")
        
        lines.append("\n💡 <code>/off ID</code>로 끄고 <code>/del ID</code>로 삭제")
        return "\n".join(lines)
    
    elif cmd == "off" and arg:
        try:
            rule_id = int(arg)
        except ValueError:
            return "❌ ID는 숫자여야 합니다"
        
        rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
        if not rule:
            return f"❌ 규칙 #{rule_id}를 찾을 수 없습니다"
        
        rule.is_enabled = False
        db.commit()
        return f"⏸️ 규칙 #{rule_id} 비활성화됨"
    
    elif cmd == "on" and arg:
        try:
            rule_id = int(arg)
        except ValueError:
            return "❌ ID는 숫자여야 합니다"
        
        rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
        if not rule:
            return f"❌ 규칙 #{rule_id}를 찾을 수 없습니다"
        
        rule.is_enabled = True
        db.commit()
        return f"▶️ 규칙 #{rule_id} 활성화됨"
    
    else:
        return """<b>ℹ️ 스팸 규칙 관리 도움말</b>
/add {키워드} - 새 키워드 추가 (콤마 구분 가능)
/del {ID} - 규칙 완전 삭제
/list - 전체 목록 및 상태 보기
/on {ID} - 특정 규칙 활성화
/off {ID} - 특정 규칙 비활성화"""
