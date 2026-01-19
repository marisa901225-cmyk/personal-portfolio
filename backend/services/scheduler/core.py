import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from backend.core.db import SessionLocal
from backend.services.news_collector import NewsCollector
from backend.services.scheduler_monitor import monitor_job_async
from backend.services.retry import sync_retry, async_retry


logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
scheduler = AsyncIOScheduler(timezone=KST)

async def job_collect_news():
    """
    주기적 뉴스 수집 작업
    """
    db: Session = SessionLocal()
    async with monitor_job_async("collect_game_news", db):
        logger.info("Starting scheduled news collection job...")
        try:
            # 1. RSS 수집
            feeds = [
                ("Inven LoL", "https://feeds.feedburner.com/inven/lol"),
            ]
            for source_name, url in feeds:
                sync_retry(NewsCollector.collect_rss)(db, url, source_name)

            # 2. SteamSpy 일반 순위 수집
            await async_retry(NewsCollector.collect_steamspy_rankings)(db)

            # 3. PandaScore 일정 수집 (e스포츠)
            await async_retry(NewsCollector.collect_pandascore_schedules)(db)

            # 4. 네이버 뉴스 수집 (E스포츠 + 경제)
            await async_retry(NewsCollector.collect_all_naver_news)(db)

            # 5. 구글 뉴스 수집 (해외 거시경제)
            await async_retry(NewsCollector.collect_all_google_news)(db)

        except Exception as e:
            logger.error(f"News collection job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("News collection job finished.")





def start_scheduler():
    if not scheduler.running:
        # 10분마다 실행 (LLM 알람 처리와 5분 오프셋 - CPU 충돌 방지)
        # LLM 농담은 :00, :10, :20... / 뉴스수집은 :05, :15, :25...
        scheduler.add_job(
            job_collect_news, 
            CronTrigger(minute='5,15,25,35,45,55'), 
            id="collect_game_news", 
            replace_existing=True
        )
        

        
        scheduler.start()
        logger.info("AsyncIOScheduler started.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("AsyncIOScheduler shutdown.")
