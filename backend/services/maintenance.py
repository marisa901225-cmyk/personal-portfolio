import logging
from datetime import datetime, timedelta
import html
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from ..core.models import SpamNews, SpamAlarm, GameNews
from ..integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

_TELEGRAM_MAX = 4096

async def generate_monthly_spam_report(db: Session):
    try:
        now = datetime.now()
        start_date = now - timedelta(days=30)

        news_total = db.query(func.count(SpamNews.id)).filter(SpamNews.created_at >= start_date).scalar() or 0
        news_reasons = (
            db.query(SpamNews.spam_reason, func.count(SpamNews.id).label("cnt"))
            .filter(SpamNews.created_at >= start_date)
            .group_by(SpamNews.spam_reason)
            .order_by(desc("cnt"))
            .all()
        )

        alarm_total = db.query(func.count(SpamAlarm.id)).filter(SpamAlarm.created_at >= start_date).scalar() or 0
        alarm_types = (
            db.query(SpamAlarm.classification, func.count(SpamAlarm.id).label("cnt"))
            .filter(SpamAlarm.created_at >= start_date)
            .group_by(SpamAlarm.classification)
            .order_by(desc("cnt"))
            .all()
        )

        report_lines = []
        report_lines.append("📊 <b>월간 스팸 운영 리포트</b>")
        report_lines.append(f"<i>기간: {start_date.strftime('%Y-%m-%d')} ~ {now.strftime('%Y-%m-%d')}</i>")
        report_lines.append("")
        report_lines.append(f"📰 <b>뉴스 스팸: {news_total}건</b>")

        # 상위 20개만 표시 (길이 폭주 방지)
        for reason, cnt in news_reasons[:20]:
            reason_txt = html.escape(reason or "분류없음", quote=False)
            report_lines.append(f"- {reason_txt}: {cnt}개")

        if len(news_reasons) > 20:
            report_lines.append(f"- 기타: {sum(c for _, c in news_reasons[20:])}개")

        report_lines.append("")
        report_lines.append(f"📱 <b>앱 알람 스팸: {alarm_total}건</b>")

        for cls, cnt in alarm_types[:20]:
            cls_txt = html.escape(cls or "분류없음", quote=False)
            report_lines.append(f"- {cls_txt}: {cnt}개")

        if len(alarm_types) > 20:
            report_lines.append(f"- 기타: {sum(c for _, c in alarm_types[20:])}개")

        report_lines.append("")
        report_lines.append("💡 <i>스팸 격리 시스템이 원활하게 작동 중입니다.</i>")

        report = "\n".join(report_lines)

        # 최후 안전망: 텔레그램 길이 제한
        if len(report) > _TELEGRAM_MAX:
            report = report[:_TELEGRAM_MAX - 20] + "\n…(생략)"

        await send_telegram_message(report)
        logger.info("Monthly spam report sent.")
    except Exception:
        logger.exception("Failed to generate monthly spam report")


async def cleanup_old_spam_data(db: Session, months: int = 1):
    try:
        now = datetime.now()
        threshold = now - timedelta(days=months * 30)

        news_deleted = (
            db.query(SpamNews)
            .filter(SpamNews.created_at < threshold)
            .delete(synchronize_session=False)
        )
        alarm_deleted = (
            db.query(SpamAlarm)
            .filter(SpamAlarm.created_at < threshold)
            .delete(synchronize_session=False)
        )

        if news_deleted or alarm_deleted:
            db.commit()
            logger.info(
                "Cleanup: Deleted %s old spam news and %s spam alarms (older than %s)",
                news_deleted, alarm_deleted, threshold
            )
        else:
            # 삭제가 없으면 커밋 생략해도 돼요
            logger.info("Cleanup: Nothing to delete.")
    except Exception:
        db.rollback()
        logger.exception("Failed to cleanup old spam data")


async def cleanup_old_news_data(db: Session):
    """
    오래된 일반 뉴스 데이터를 정리한다.
    - 경제 뉴스 (Economy): 90일 보관
    - 기타 뉴스 (LoL, Steam 등): 30일 보관
    """
    try:
        now = datetime.now()
        economy_threshold = now - timedelta(days=90)
        general_threshold = now - timedelta(days=30)

        # 1. 경제 뉴스 정리 (90일 기준)
        economy_deleted = (
            db.query(GameNews)
            .filter(GameNews.category_tag == "Economy")
            .filter(GameNews.published_at < economy_threshold)
            .delete(synchronize_session=False)
        )

        # 2. 나머지 뉴스 정리 (30일 기준)
        general_deleted = (
            db.query(GameNews)
            .filter(GameNews.category_tag != "Economy")
            .filter(GameNews.published_at < general_threshold)
            .delete(synchronize_session=False)
        )

        if economy_deleted or general_deleted:
            db.commit()
            logger.info(
                "Cleanup: Deleted %s old economy news (older than %s) and %s general news (older than %s)",
                economy_deleted, economy_threshold, general_deleted, general_threshold
            )
        else:
            logger.info("Cleanup: No old news to delete.")
    except Exception:
        db.rollback()
        logger.exception("Failed to cleanup old news data")
