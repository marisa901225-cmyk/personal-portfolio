# backend/services/alarm_service.py
# 모듈화된 alarm 처리 서비스 프록시
# 실제 로직은 alarm/ 하위 모듈들에 구현됨
import logging
from typing import List
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 모듈에서 함수 임포트
from .alarm.llm_logic import summarize_with_llm, summarize_expenses_with_llm
from .alarm.processor import process_pending_alarms
from .alarm.filters import mask_sensitive_info
from .alarm.sanitizer import escape_html_preserve_urls, clean_exaone_tokens
from .alarm.parsers import parse_card_approval
from .alarm.match_notifier import check_upcoming_matches


class AlarmService:
    """알람 처리 서비스 (프록시 클래스)"""
    
    @classmethod
    async def summarize_with_llm(cls, items: List[dict]) -> str:
        """LLM을 사용하여 알림 요약 또는 랜덤 메시지 생성"""
        return await summarize_with_llm(items)
    
    @classmethod
    async def summarize_expenses_with_llm(cls, expenses: List[dict]) -> str:
        """가계부 내역 분석 코멘트 생성"""
        return await summarize_expenses_with_llm(expenses)
    
    @classmethod
    async def process_pending_alarms(cls, db: Session):
        """대기 중인 알람 처리 (필터링, 요약, 텔레그램 전송)"""
        return await process_pending_alarms(db)

    @classmethod
    async def generate_daily_catchphrases(cls):
        """매일 또는 주기적으로 e스포츠 전용 캐치프레이즈를 생성한다 (폴백 기반)."""
        from .alarm.catchphrases import generate_daily_catchphrases as gen_fn
        return await gen_fn()
