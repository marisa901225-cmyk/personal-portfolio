import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from .core.db import SessionLocal
from .services.news_collector import NewsCollector

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def job_collect_news():
    """
    주기적 뉴스 수집 작업
    """
    logger.info("Starting scheduled news collection job...")
    db: Session = SessionLocal()
    try:
        # 1. RSS 수집
        feeds = [
            ("Inven LoL", "https://feeds.feedburner.com/inven/lol"),
        ]
        for source_name, url in feeds:
            NewsCollector.collect_rss(db, url, source_name)
            
        # 2. SteamSpy 일반 순위 수집
        await NewsCollector.collect_steamspy_rankings(db)
        
        # 3. PandaScore 일정 수집 (e스포츠)
        await NewsCollector.collect_pandascore_schedules(db)
        
        # 4. 네이버 뉴스 수집 (E스포츠 + 경제)
        await NewsCollector.collect_all_naver_news(db)
        
        # 5. 구글 뉴스 수집 (해외 거시경제)
        await NewsCollector.collect_all_google_news(db)
            
    except Exception as e:
        logger.error(f"News collection job failed: {e}")
    finally:
        db.close()
        logger.info("News collection job finished.")


def start_scheduler():
    if not scheduler.running:
        # 1시간마다 실행
        scheduler.add_job(
            job_collect_news, 
            IntervalTrigger(hours=1), 
            id="collect_game_news", 
            replace_existing=True
        )
        
        # 스팀 트렌드 요약 (자동 발송 제거 -> 채팅 RAG로 위임)
        
        scheduler.start()
        logger.info("AsyncIOScheduler started.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("AsyncIOScheduler shutdown.")
