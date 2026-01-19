"""
자연어 질의 처리 핸들러
게임 트렌드, E스포츠, 경제 뉴스, 일반 대화
"""
import os
import re
import json
import html
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from ...core.models import User, UserMemory
from ...core.db import SessionLocal
from ...core.time_utils import utcnow
from ...integrations.telegram import send_telegram_message
from ...services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

# 채팅 세션 관리 (메모리 내 저장, 재시작 시 초기화됨)
_chat_sessions = {}  # chat_id -> list of messages
MAX_SESSION_MESSAGES = 10

PAID_CHAT_MODEL = os.getenv("TELEGRAM_PAID_CHAT_MODEL") or os.getenv("AI_REPORT_MODEL") or "gpt-5-nano"


def classify_query(text: str) -> str:
    """사용자 질문 유형 분류"""
    text_lower = text.lower()
    
    # 1. 리포트 키워드
    if any(kw in text_lower for kw in ['리포트', '보고서', 'report', '자산', '수익률', '가계부', '지출']):
        return 'report'

    # 2. E스포츠 키워드
    if any(kw in text_lower for kw in ['t1', 'skt', '티원', '젠지', 'geng', 'gen.g', 'lol', '롤', 
                                        'lck', '발로란트', 'valorant', 'vct', '경기', '일정', 
                                        '월즈', 'worlds', '챌린저스', '퍼시픽']):
        return 'esports_schedule'
    
    # 3. 게임 트렌드 키워드
    if any(kw in text_lower for kw in ['게임', '스팀', 'steam', '신작', '트렌드', '인기', '출시', 
                                        '추천', '플스', 'ps5', 'playstation', '닌텐도', 'switch']):
        return 'game_trend'
    
    # 4. 경제 키워드
    if any(kw in text_lower for kw in ['미국', '유럽', '환율', 'fomc', 'ecb', 's&p', '나스닥', '금리',
                                        'cpi', 'etf', '달러', '유로', '채권', '국채', 'treasury', '코스피',
                                        '코스닥', '주식', '경제', '인플레', '경기', '불황', '호황']):
        return 'economy_news'
    
    # 5. 기억하기 키워드
    if any(kw in text_lower for kw in ['기억해', '저장해', '기억해줘', '기억해라', '기억해주길', 'remember']):
        return 'memory_store'

    return 'general_chat'


def reset_session(chat_id: str):
    """대화 세션 초기화"""
    if chat_id in _chat_sessions:
        _chat_sessions[chat_id] = []


async def handle_query(text: str, chat_id: str) -> None:
    """자연어 질의 처리 메인 함수"""
    query_type = classify_query(text)
    logger.info(f"Query classified as: {query_type}")
    
    if query_type == "memory_store":
        await _handle_memory_store(text)
    elif query_type == "game_trend":
        await _handle_game_trend(text)
    elif query_type == "report":
        await _handle_report(text)
    elif query_type == "esports_schedule":
        await _handle_esports(text)
    elif query_type == "economy_news":
        await _handle_economy(text)
    else:
        await _handle_general_chat(text, chat_id)


async def _handle_memory_store(text: str):
    """장기 기억 저장"""
    from ...services.llm_service import LLMService
    llm = LLMService.get_instance()
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if not user:
            user = User(name="Owner")
            db.add(user)
            db.commit()
        
        extraction_prompt = load_prompt("memory_extractor", text=text)
        extraction_res = llm.generate_paid_chat(
            [{"role": "user", "content": extraction_prompt}],
            model=PAID_CHAT_MODEL,
        )
        
        try:
            json_match = re.search(r'\{.*\}', extraction_res, re.DOTALL)
            mem_data = json.loads(json_match.group()) if json_match else json.loads(extraction_res)
        except Exception:
            mem_data = {"content": text, "category": "general", "key": None, "importance": 1, "ttl_days": 0}

        content = mem_data.get("content", text)
        category = mem_data.get("category", "general")
        key = mem_data.get("key")
        importance = mem_data.get("importance", 1)
        ttl_days = mem_data.get("ttl_days", 0)
        expires_at = utcnow() + timedelta(days=ttl_days) if ttl_days > 0 else None

        existing = db.query(UserMemory).filter(UserMemory.user_id == user.id, UserMemory.key == key).first() if key else None
        
        if existing:
            existing.content = content
            existing.category = category
            existing.importance = importance
            existing.expires_at = expires_at
            existing.updated_at = utcnow()
            db.commit()
            await send_telegram_message(f"🔄 기존 기억을 업데이트했습니다: \"{content}\" (키: {key})")
        else:
            new_mem = UserMemory(user_id=user.id, content=content, category=category, 
                                  key=key, importance=importance, expires_at=expires_at)
            db.add(new_mem)
            db.commit()
            msg = f"✅ 기억하겠습니다: \"{content}\""
            if category != "general":
                msg += f" (분류: {category})"
            await send_telegram_message(msg)
    except Exception as e:
        logger.error(f"Memory store failed: {e}")
        await send_telegram_message("기억하는 중에 오류가 발생했습니다. 😅")
    finally:
        db.close()


async def _handle_game_trend(text: str):
    """게임 트렌드 질의"""
    from ...services.news.refiner import refine_game_trends_with_duckdb
    from ...services.llm_service import LLMService
    
    context_text = refine_game_trends_with_duckdb(text)
    prompt = load_prompt("game_trend", text=text, context=context_text)
    
    llm = LLMService.get_instance()
    messages = [
        {"role": "system", "content": "당신은 게임 트렌드 분석가이자 스팀(Steam) 전문가입니다."},
        {"role": "user", "content": prompt}
    ]
    
    response_text = llm.generate_chat(messages, max_tokens=1536)
    await send_telegram_message(_format_for_telegram(response_text))


async def _handle_report(text: str):
    """투자/가계부 리포트"""
    from ...services.report_service import resolve_ai_report_prompt, generate_ai_report_text
    db = SessionLocal()
    try:
        period, prompt = resolve_ai_report_prompt(db, query=text)
        await send_telegram_message(f"⏳ <b>{period.label}</b> 리포트를 생성 중입니다... (AI 분석 중)")
        
        report_ai_res = await generate_ai_report_text(period, prompt)
        await send_telegram_message(_format_for_telegram(report_ai_res.report))
    except Exception as e:
        logger.error(f"AI Report generation failed: {e}")
        await send_telegram_message("리포트 생성 중 오류가 발생했습니다. 😅 (데이터 부족 또는 AI 서버 일시 장애)")
    finally:
        db.close()


async def _handle_esports(text: str):
    """E스포츠 일정"""
    from ...services.news_collector import NewsCollector
    
    context_text = NewsCollector.refine_schedules_with_duckdb(text)

    no_data_markers = {
        "검색된 관련 일정이 없습니다.",
        "뉴스 정제 중 오류가 발생했습니다.",
    }
    if not context_text or context_text.strip() in no_data_markers:
        await send_telegram_message(
            _format_for_telegram(
                "DB에서 조건에 맞는 e스포츠 일정이 없습니다.\n"
                "- 스케줄 수집(PandaScore) / 태그(LCK 등) / event_time 타임존을 먼저 확인해 주세요.\n"
                "- 데이터가 들어온 뒤 다시 물어보면 DB 기준으로만 답변할게요."
            )
        )
        return

    from ...services.llm_service import LLMService
    prompt = load_prompt("esports", text=text, context=context_text)
    
    llm = LLMService.get_instance()
    messages = [
        {"role": "system", "content": "당신은 e스포츠 전문가이자 사용자의 개인 비서입니다. 친절하고 위트 있게 답변하세요."},
        {"role": "user", "content": prompt}
    ]
    
    response_text = llm.generate_chat(messages, max_tokens=768)
    await send_telegram_message(_format_for_telegram(response_text))


async def _handle_economy(text: str):
    """경제 뉴스"""
    from ...services.news_collector import NewsCollector
    from ...services.llm_service import LLMService
    
    context_text = NewsCollector.refine_economy_news_with_duckdb(text)
    prompt = load_prompt("economy", text=text, context=context_text)
    
    llm = LLMService.get_instance()
    messages = [
        {"role": "system", "content": "당신은 글로벌 경제 전문가입니다. 어려운 내용도 쉽게 설명해 주세요."},
        {"role": "user", "content": prompt}
    ]
    
    response_text = llm.generate_chat(messages, max_tokens=768)
    await send_telegram_message(_format_for_telegram(response_text))


async def _handle_general_chat(text: str, chat_id: str):
    """일반 대화 (유료 모델 사용)"""
    from ...services.llm_service import LLMService
    llm = LLMService.get_instance()
    
    session = _chat_sessions.get(chat_id, [])
    if len(session) >= MAX_SESSION_MESSAGES:
        session = []

    # 장기 기억 조회
    db = SessionLocal()
    memories_text = ""
    try:
        user = db.query(User).first()
        if user:
            now = utcnow()
            memories = db.query(UserMemory).filter(
                UserMemory.user_id == user.id,
                (UserMemory.expires_at == None) | (UserMemory.expires_at > now)
            ).order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc()).limit(10).all()
            
            if memories:
                cat_map = {}
                for m in memories:
                    if m.category not in cat_map: cat_map[m.category] = []
                    cat_map[m.category].append(m.content)
                
                lines = ["[사용자에 대한 장기 기억]"]
                for cat, m_list in cat_map.items():
                    lines.append(f"• {cat.upper()}:")
                    for content in m_list:
                        lines.append(f"  - {content}")
                memories_text = "\n".join(lines)
    finally:
        db.close()

    session.append({"role": "user", "content": text})
    system_content = load_prompt("general_chat")
    
    is_simple_greeting = len(text) < 5 and any(kw in text.lower() for kw in ['안녕', 'hi', 'hello', 'ㅎㅇ'])
    if memories_text and not is_simple_greeting:
        system_content += "\n\n" + memories_text

    api_messages = [{"role": "system", "content": system_content}] + session
    response_text = llm.generate_paid_chat(api_messages, model=PAID_CHAT_MODEL)
    
    if response_text:
        session.append({"role": "assistant", "content": response_text})
        _chat_sessions[chat_id] = session
    else:
        response_text = "유료 AI 서버 응답 실패. 잠시 후 다시 시도해 주세요. 😅"
    
    await send_telegram_message(_format_for_telegram(response_text))


def _format_for_telegram(text: str) -> str:
    """AI 응답을 텔레그램 HTML 형식으로 변환"""
    from ...services.alarm.sanitizer import clean_exaone_tokens
    
    text = clean_exaone_tokens(text)
    safe_text = html.escape(text)
    safe_text = re.sub(r'^###\s+(.+)$', r'<b>\1</b>', safe_text, flags=re.MULTILINE)
    safe_text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe_text)
    safe_text = re.sub(r'^-\s+', '• ', safe_text, flags=re.MULTILINE)
    
    return safe_text.strip()
