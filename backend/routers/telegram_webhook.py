"""
Telegram Webhook Router - 텔레그램 봇 명령어 처리
/spam add {pattern} - 스팸 규칙 추가
/spam del {id} - 스팸 규칙 삭제
/spam list - 스팸 규칙 목록
"""
import os
import logging
import html
import re
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session

from ..core.db import SessionLocal
from ..core.models import SpamRule
from ..integrations.telegram import send_telegram_message

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

# 환경변수에서 시크릿 토큰과 허용된 채팅 ID 로드
WEBHOOK_SECRET = os.getenv("X_TELEGRAM_BOT_API_SECRET_TOKEN") or os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")


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
        logger.warning(
            "Invalid webhook secret token (len=%s)",
            len(secret_header) if secret_header else 0,
        )
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
        # (A) 명령어 처리 Flow
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0] if len(parts) > 0 else ""
        arg = parts[1] if len(parts) > 1 else ""
        
        # /spam 접두사 지원 (하이브리드)
        if cmd == "spam":
            parts = arg.split(maxsplit=1)
            cmd = parts[0] if len(parts) > 0 else ""
            arg = parts[1] if len(parts) > 1 else ""
        
        # 명령어별 처리
        if cmd == "report":
            from ..services.reporting.template import build_telegram_steam_trend_message
            response_text = build_telegram_steam_trend_message(arg)
            await send_telegram_message(response_text)
            return {"ok": True}
        
        # 지원하는 명령어 리스트
        SUPPORTED_CMDS = ["add", "del", "list", "on", "off", "help", "model"]
        if cmd not in SUPPORTED_CMDS:
            return {"ok": True}
        
        db = SessionLocal()
        try:
            if cmd == "model":
                # /model 명령어는 별도 핸들러
                model_parts = arg.split(maxsplit=1)
                response_text = await handle_model_command(model_parts)
            else:
                response_text = await handle_spam_command(cmd, arg, db)
            
            # 규칙 변경(add, del, on, off)이 있으면 AI 모델 재학습 트리거
            if cmd in ["add", "del", "on", "off"] and any(icon in response_text for icon in ["✅", "🗑️", "⏸️", "▶️"]):
                from ..services.spam_trainer import train_spam_model
                if train_spam_model():
                    response_text += "\n🔄 <i>AI 모델이 최신 규칙으로 재학습되었습니다.</i>"
            
            await send_telegram_message(response_text)
        finally:
            db.close()
    else:
        # (B) 자연어 처리 Flow
        logger.info("Natural language query received (len=%s)", len(text))
        query_type = classify_query(text)
        logger.info(f"Query classified as: {query_type}")
        
        # 분류에 따른 핸들러 매핑
        # 1. 게임 트렌드 (템플릿 기반 - 단일화된 경로)
        # 1. 게임 트렌드 (EXAONE 로컬 요약)
        if query_type == "game_trend":
            from ..services.news.refiner import refine_game_trends_with_duckdb
            from ..services.llm_service import LLMService
            
            # (1) DuckDB 데이터 조회
            context_text = refine_game_trends_with_duckdb(text)
            
            # (2) 프롬프트 구성
            prompt = _get_game_trend_prompt(text, context_text)
            
            # (3) 로컬 LLM 생성
            llm = LLMService.get_instance()
            messages = [
                {"role": "system", "content": "당신은 게임 트렌드 분석가이자 스팀(Steam) 전문가입니다."},
                {"role": "user", "content": prompt}
            ]
            
            response_text = llm.generate_chat(messages, max_tokens=1536)
            formatted_response = _format_for_telegram(response_text)
            await send_telegram_message(formatted_response)
            return {"ok": True}
            
        # 2. 투자/가계부 리포트 (LLM 기반 서술형)
        if query_type == "report":
            from ..services.report_service import resolve_ai_report_prompt, generate_ai_report_text
            db = SessionLocal()
            try:
                # (1) 리포트 생성을 위한 프롬프트 및 기간 해석
                period, prompt = resolve_ai_report_prompt(db, query=text)
                await send_telegram_message(f"⏳ <b>{period.label}</b> 리포트를 생성 중입니다... (AI 분석 중)")
                
                # (2) AI API 호출하여 서술형 리포트 생성
                report_ai_res = await generate_ai_report_text(period, prompt)
                raw_report = report_ai_res.report
                
                # (3) 텔레그램용 HTML 변환 (Markdown -> HTML 태그)
                formatted_report = _format_for_telegram(raw_report)
                await send_telegram_message(formatted_report)
            except Exception as e:
                logger.error(f"AI Report generation failed: {e}")
                await send_telegram_message("리포트 생성 중 오류가 발생했습니다. 😅 (데이터 부족 또는 AI 서버 일시 장애)")
            finally:
                db.close()
            return {"ok": True}

        # 3. 그 외 LLM 기반 질의 처리 (E스포츠, 경제 뉴스, 일반 대화)
        try:
            from ..services.llm_service import LLMService
            llm = LLMService.get_instance()
            
            # (1) Context 및 Prompt 구성
            system_instruction = ""
            user_prompt = ""
            
            if query_type == 'esports_schedule':
                from ..services.news_collector import NewsCollector
                context_text = NewsCollector.refine_schedules_with_duckdb(text)
                system_instruction = "당신은 e스포츠 전문가이자 사용자의 개인 비서입니다. 친절하고 위트 있게 답변하세요."
                user_prompt = _get_esports_prompt(text, context_text)
            
            elif query_type == 'economy_news':
                from ..services.news_collector import NewsCollector
                context_text = NewsCollector.refine_economy_news_with_duckdb(text)
                system_instruction = "당신은 글로벌 경제 전문가입니다. 어려운 내용도 쉽게 설명해 주세요."
                user_prompt = _get_economy_prompt(text, context_text)
            
            else: # general_chat
                system_instruction = "당신은 친절하고 유머러스한 개인 비서입니다."
                user_prompt = text
            
            # (2) 로컬 EXAONE 호출 (Chat Completion)
            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ]
            response_text = llm.generate_chat(messages, max_tokens=1536)
            
            if not response_text:
                response_text = "죄송합니다. 답변을 생성하는 중에 문제가 발생했습니다. 😅"
            
            formatted_response = _format_for_telegram(response_text)
            await send_telegram_message(formatted_response)
            
        except Exception as e:
            logger.error(f"Query processing failed: {e}")
            await send_telegram_message("답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.")
    
    return {"ok": True}


def _get_game_trend_prompt(text: str, context: str) -> str:
    return f"""
[제공된 스팀 게임 트렌드 데이터]
{context}

[사용자의 질문]
{text}

[답변 규칙]
- 데이터를 기반으로 신작이나 인기 게임을 3-4개 정도 추천해 주세요.
- 각 게임의 특징을 짧고 강렬하게 요약하여 흥미를 유발하세요.
- 너무 길지 않게 핵심만 전달하여 빠르게 답변하세요.
- EXAONE으로서의 위트 있는 말투를 보여주세요.
"""


# 프롬프트 생성 헬퍼 함수들 (현재 메인 로직에서 직접 generate_chat 사용, 레거시용)
def _get_esports_prompt(text: str, context: str) -> str:
    return f"""
사용자의 질문과 아래 제공된 경기 일정 데이터를 바탕으로 친절하고 명확하게 답변해 주세요.

[제공된 경기 일정 데이터]
{context}

[사용자의 질문]
{text}

[답변 규칙]
- 한국어로 답변하세요.
- 데이터에 있는 내용을 기반으로 정확하게 안내하세요. 만약 데이터에 없는 내용이라면 모른다고 정직하게 말하세요.
- 친절하고 위트 있는 말투를 사용하세요.
- 일시 정보를 포함하여 경기 정보를 깔끔하게 정리해 주세요.
"""

def _get_economy_prompt(text: str, context: str) -> str:
    return f"""
아래 제공된 경제 뉴스 데이터를 바탕으로 사용자의 질문에 친절하고 명확하게 답변해 주세요.

[제공된 경제 뉴스 데이터]
{context}

[사용자의 질문]
{text}

[답변 규칙]
- 한국어로 답변하세요.
- 영문 뉴스 제목이라면 핵심만 번역하여 설명하세요.
- 데이터에 있는 내용을 기반으로 정확하게 안내하세요. 데이터에 없는 내용은 모른다고 말하세요.
- 친절하고 위트 있는 말투를 사용하세요.
"""

def _get_general_chat_prompt(text: str) -> str:
    return f"""
사용자의 메시지에 자연스럽고 위트 있게 답변해 주세요.

[사용자 메시지]
{text}
"""


def _format_for_telegram(text: str) -> str:
    """
    AI 응답을 텔레그램 HTML 형식으로 변환한다.
    - HTML 특수문자 이스케이프 (<, >, &)
    - ### 제목 -> <b>제목</b>
    - **강조** -> <b>강조</b>
    - 불렛 포인트(-) -> •
    """
    # 1. 기본 HTML 특수문자 이스케이프 (태그 깨짐 방지)
    safe_text = html.escape(text)
    
    # 2. 섹션 제목 변환: ### 제목 -> <b>제목</b>
    safe_text = re.sub(r'^###\s+(.+)$', r'<b>\1</b>', safe_text, flags=re.MULTILINE)
    
    # 3. 굵게 변환: **텍스트** -> <b>텍스트</b>
    safe_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe_text)
    
    # 4. 불렛 포인트 변환: 줄 시작의 - -> •
    safe_text = re.sub(r'^-\s+', '• ', safe_text, flags=re.MULTILINE)
    
    return safe_text


def classify_query(text: str) -> str:
    """
    사용자 질문 유형 분류
    - 'esports_schedule': E스포츠 경기 일정 관련
    - 'game_trend': 게임 신작/트렌드 관련
    - 'economy_news': 국내/외 경제 뉴스 관련
    - 'report': 투자/가계부 리포트 요청
    - 'general_chat': 일반 대화
    """
    text_lower = text.lower()
    
    # 1. 리포트 키워드 (투자, 가계부, 자산 리포트)
    report_keywords = ['리포트', '보고서', 'report', '자산', '수익률', '가계부', '지출']
    if any(kw in text_lower for kw in report_keywords):
        return 'report'

    # 2. E스포츠 키워드
    esports_keywords = ['t1', 'skt', '티원', '젠지', 'geng', 'gen.g', 'lol', '롤', 
                        'lck', '발로란트', 'valorant', 'vct', '경기', '일정', 
                        '월즈', 'worlds', '챌린저스', '퍼시픽']
    if any(kw in text_lower for kw in esports_keywords):
        return 'esports_schedule'
    
    # 3. 게임 트렌드 키워드
    game_keywords = ['게임', '스팀', 'steam', '신작', '트렌드', '인기', '출시', 
                     '추천', '플스', 'ps5', 'playstation', '닌텐도', 'switch']
    if any(kw in text_lower for kw in game_keywords):
        return 'game_trend'
    
    # 4. 해외 + 국내 경제 키워드
    economy_keywords = ['미국', '유럽', '환율', 'fomc', 'ecb', 's&p', '나스닥', '금리',
                        'cpi', 'etf', '달러', '유로', '채권', '국채', 'treasury', '코스피',
                        '코스닥', '주식', '경제', '인플레', '경기', '불황', '호황']
    if any(kw in text_lower for kw in economy_keywords):
        return 'economy_news'
    
    # 기타 일반 대화
    return 'general_chat'



async def handle_model_command(parts: list) -> str:
    """/model 명령어 처리"""
    from ..services.llm_service import LLMService
    llm = LLMService.get_instance()
    
    subcmd = parts[0] if len(parts) > 0 else "목록"
    arg = parts[1] if len(parts) > 1 else ""
    
    # 모델 별칭 매핑
    MODEL_ALIASES = {
        "E3.5": "EXAONE-3.5-2.4B-Instruct-BF16.gguf",
        "E4": "EXAONE-4.0-1.2B-BF16.gguf",
        "G3": "gemma-3-4b-it-Q3_K_M.gguf",
        "G4": "gemma-3-4b-it-q4_k_m.gguf"
    }
    
    if subcmd in ["list", "목록", "리스트"]:
        models = llm.list_available_models()
        current = llm.get_current_model()
        
        if not models:
            return "📁 사용 가능한 GGUF 모델이 없습니다. (backend/data 디렉토리 확인)"
        
        lines = ["<b>🤖 사용 가능한 모델 목록</b>"]
        # 역방향 매핑 준비
        rev_aliases = {v: k for k, v in MODEL_ALIASES.items()}
        
        for m in models:
            is_active = " (활성)" if m == current else ""
            fname = os.path.basename(m)
            alias = rev_aliases.get(fname)
            alias_str = f" [<b>{alias}</b>]" if alias else ""
            lines.append(f"• <code>{fname}</code>{alias_str}{is_active}")
        
        lines.append("\n💡 <code>/model 교체 별칭</code> 또는 <code>파일명</code>으로 교체")
        return "\n".join(lines)
    
    elif subcmd in ["switch", "교체", "변경", "선택"] and arg:
        # 1. 별칭 우선 확인
        target_file = MODEL_ALIASES.get(arg)
        
        # 2. 별칭이 없으면 파일명 부분 일치 검색
        if not target_file:
            available_models = llm.list_available_models()
            for m in available_models:
                fname = os.path.basename(m)
                if arg.lower() in fname.lower():
                    target_file = fname
                    break
        
        if not target_file:
            target_file = arg # 검색 실패 시 입력값 그대로 사용
            
        # 파일 경로 구성
        full_path = target_file if target_file.startswith("backend/data/") else os.path.join("backend/data", target_file)
        if not full_path.endswith(".gguf") and "." not in target_file:
            full_path += ".gguf"
            
        if llm.switch_model(full_path):
            return f"✅ 모델이 교체되었습니다: <code>{os.path.basename(full_path)}</code>"
        else:
            if not os.path.exists(full_path):
                return f"❌ 모델 교체 실패: <code>{arg}</code>와 일치하는 모델을 찾을 수 없습니다."
            last_error = llm.get_last_error()
            if last_error:
                return f"❌ 모델 교체 실패: <code>{os.path.basename(full_path)}</code> 로드 오류 ({last_error})"
            return f"❌ 모델 교체 실패: <code>{os.path.basename(full_path)}</code> 로드에 실패했습니다."
            
    return "ℹ️ 사용법: /model 목록 또는 /model 교체 {별칭|파일명}"


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
        return """<b>ℹ️ 봇 명령어 도움말</b>
/report {내용} - 스팀 게임 트렌드 리포트 생성 (DuckDB 기반)
(예: /report, /report 신작)

/model 목록 - 사용 가능한 LLM 모델 목록
/model 교체 {별칭|파일명} - 실시간 모델 교체

<b>스팸 규칙 관리</b>
/add {키워드} - 새 키워드 추가 (콤마 구분 가능)
/del {ID} - 규칙 완전 삭제
/list - 전체 목록 및 상태 보기
/on {ID} - 특정 규칙 활성화
/off {ID} - 특정 규칙 비활성화"""
