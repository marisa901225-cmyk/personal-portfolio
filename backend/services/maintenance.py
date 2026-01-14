"""
시스템 유지보수 서비스 (월간 리포트 및 데이터 정리)
"""
import logging
import os
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..core.models import SpamNews, SpamAlarm
from ..integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

async def generate_monthly_spam_report(db: Session):
    """
    한 달간의 스팸 통계를 집계하여 텔레그램으로 전송한다.
    """
    try:
        # 지난 한 달 기준 (오늘부터 30일 전)
        start_date = datetime.now() - timedelta(days=30)
        
        # 1. 뉴스 스팸 통계
        news_total = db.query(SpamNews).filter(SpamNews.created_at >= start_date).count()
        news_reasons = db.query(SpamNews.spam_reason, func.count(SpamNews.id))\
            .filter(SpamNews.created_at >= start_date)\
            .group_by(SpamNews.spam_reason).all()
        
        # 2. 알람 스팸 통계
        alarm_total = db.query(SpamAlarm).filter(SpamAlarm.created_at >= start_date).count()
        alarm_types = db.query(SpamAlarm.classification, func.count(SpamAlarm.id))\
            .filter(SpamAlarm.created_at >= start_date)\
            .group_by(SpamAlarm.classification).all()

        # 메시지 구성
        report = f"📊 <b>월간 스팸 운영 리포트</b>\n"
        report += f"<i>기간: {start_date.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')}</i>\n\n"
        
        report += f"📰 <b>뉴스 스팸: {news_total}건</b>\n"
        for reason, count in news_reasons:
            report += f"- {reason or '분류없음'}: {count}개\n"
        
        report += f"\n📱 <b>앱 알람 스팸: {alarm_total}건</b>\n"
        for cls, count in alarm_types:
            report += f"- {cls or '분류없음'}: {count}개\n"
        
        report += f"\n💡 <i>스팸 격리 시스템이 원활하게 작동 중입니다.</i>"
        
        await send_telegram_message(report)
        logger.info("Monthly spam report sent.")
        
    except Exception as e:
        logger.error(f"Failed to generate monthly spam report: {e}")

async def cleanup_old_spam_data(db: Session, months: int = 3):
    """
    N개월 이상 지난 스팸 데이터를 삭제하여 DB 용량을 관리한다.
    """
    try:
        threshold = datetime.now() - timedelta(days=months * 30)
        
        # SpamNews 삭제
        news_deleted = db.query(SpamNews).filter(SpamNews.created_at < threshold).delete()
        
        # SpamAlarm 삭제
        alarm_deleted = db.query(SpamAlarm).filter(SpamAlarm.created_at < threshold).delete()
        
        if news_deleted > 0 or alarm_deleted > 0:
            db.commit()
            logger.info(f"Cleanup: Deleted {news_deleted} old spam news and {alarm_deleted} spam alarms (older than {threshold}).")
    except Exception as e:
        logger.error(f"Failed to cleanup old spam data: {e}")
        db.rollback()
