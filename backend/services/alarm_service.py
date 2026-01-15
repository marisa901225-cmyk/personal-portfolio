import os
import logging
from typing import List
from sqlalchemy.orm import Session

# New specialized modules
from .alarm.llm_logic import summarize_with_llm, summarize_expenses_with_llm, generate_daily_catchphrases
from .alarm.match_notifier import check_upcoming_matches
from .alarm.processor import process_alarms_batch

logger = logging.getLogger(__name__)

# Constants
CATCHPHRASES_FILE = os.path.join(os.path.dirname(__file__), "../data/esports_catchphrases.json")

class AlarmService:
    @classmethod
    async def summarize_with_llm(cls, items: List[dict]) -> str:
        """3단계: Local LLM을 사용하여 알림 요약 또는 랜덤 메시지 생성"""
        return await summarize_with_llm(items)

    @classmethod
    async def summarize_expenses_with_llm(cls, expenses: List[dict]) -> str:
        """가계부 내역(결제 승인) 분석 코멘트 생성"""
        return await summarize_expenses_with_llm(expenses)

    @classmethod
    async def generate_daily_catchphrases(cls):
        """매일 밤 e스포츠 멘트 생성"""
        await generate_daily_catchphrases(CATCHPHRASES_FILE)

    @classmethod
    async def check_upcoming_matches(cls, db: Session, window_minutes: int = 5) -> bool:
        """곧 시작할 e스포츠 경기 알람 체크"""
        return await check_upcoming_matches(db, CATCHPHRASES_FILE, window_minutes)

    @classmethod
    async def process_pending_alarms(cls, db: Session):
        """수신된 알림들을 처리 (필터링, 가계부 저장, 요약 전송)"""
        # 경기 알람은 절대 메인 배치를 막지 못하게 (최대 3초 대기)
        try:
            import asyncio
            await asyncio.wait_for(cls.check_upcoming_matches(db), timeout=3.0)
        except Exception:
            logger.exception("Upcoming match check failed or timed out; continuing with normal alarm batch")

        # 일반 알람 배치 처리
        await process_alarms_batch(db)
