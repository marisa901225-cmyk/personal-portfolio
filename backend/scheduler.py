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
            
    except Exception as e:
        logger.error(f"News collection job failed: {e}")
    finally:
        db.close()
        logger.info("News collection job finished.")

async def job_steam_trends_summary():
    """
    매일 1회 스팀 신작 트렌드 AI 요약 리포트 생성 및 전송
    """
    logger.info("Starting daily Steam trends summary job...")
    db: Session = SessionLocal()
    try:
        # 1. 먼저 최신 스팀 트렌드 수집하여 DB 저장 (DuckDB 정제용)
        await NewsCollector.collect_steam_new_trends(db)
        
        # 2. DuckDB 정제 후 AI 요약 리포트 생성 및 전송
        await NewsCollector.generate_steam_trend_summary(db)
    except Exception as e:
        logger.error(f"Steam trends summary job failed: {e}")
    finally:
        db.close()
        logger.info("Steam trends summary job finished.")

def start_scheduler():
    if not scheduler.running:
        # 1시간마다 실행
        scheduler.add_job(
            job_collect_news, 
            IntervalTrigger(hours=1), 
            id="collect_game_news", 
            replace_existing=True
        )
        
        # 2. 매일 오전 10시 스팀 신작 트렌드 요약 (KST)
        scheduler.add_job(
            job_steam_trends_summary,
            CronTrigger(hour=10, minute=0),
            id="steam_trends_summary",
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("AsyncIOScheduler started.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("AsyncIOScheduler shutdown.")
