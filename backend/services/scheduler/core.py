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
    with SessionLocal() as db:
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

                # 4. 네이버 뉴스 수집 (E스포츠 + 경제)
                await async_retry(NewsCollector.collect_all_naver_news)(db)

                # 5. 구글 뉴스 수집 (해외 거시경제)
                await async_retry(NewsCollector.collect_all_google_news)(db)

            except Exception as e:
                logger.error(f"News collection job failed: {e}", exc_info=True)
                raise e
            finally:
                logger.info("News collection job finished.")

async def job_morning_briefing():
    """
    매일 아침 7시 모닝 브리핑 (날씨 -> 알림 요약 순차 실행)
    """
    from backend.services.news.weather import send_weather_notification
    from backend.services.alarm.processor import process_pending_alarms
    from backend.core.db import SessionLocal
    from backend.services.retry import async_retry
    
    logger.info("Starting Morning Briefing (Weather -> Alarm Summary)...")
    
    # 1. 날씨 알림 전송
    try:
        await async_retry(send_weather_notification)()
    except Exception as e:
        logger.error(f"Morning Briefing: Weather notification failed: {e}")
        
    # 2. 알림 요약 처리 (기존 7시 작업 통합)
    with SessionLocal() as db:
        try:
            await async_retry(process_pending_alarms)(db)
        except Exception as e:
            logger.error(f"Morning Briefing: Alarm processing failed: {e}", exc_info=True)
    
    logger.info("Morning Briefing completed.")





def start_scheduler():
    if not scheduler.running:
        # 30분마다 실행 (LLM 알람 처리와 겹침 방지)
        # LLM 농담은 :00, :10, :20... / 뉴스수집은 :07, :37...
        scheduler.add_job(
            job_collect_news, 
            CronTrigger(minute='7,37'), 
            id="collect_game_news", 
            replace_existing=True,
            max_instances=1
        )
        
        # 매일 아침 7시 모닝 브리핑 (날씨 -> 알림 요약 순차 실행)
        scheduler.add_job(
            job_morning_briefing,
            CronTrigger(hour=7, minute=0),
            id="morning_briefing",
            replace_existing=True,
            max_instances=1
        )
        

        
        scheduler.start()
        logger.info("AsyncIOScheduler started.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("AsyncIOScheduler shutdown.")
