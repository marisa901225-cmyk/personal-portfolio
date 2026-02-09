import asyncio
import logging
import os
import sys
import subprocess
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from pytz import timezone

# .env 파일 로드
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
load_dotenv(os.path.join(PROJECT_ROOT, "backend/.env"))

# 프로젝트 루트를 패스에 추가 (backend 패키지 임포트용)
sys.path.append(PROJECT_ROOT)

from backend.services.llm_service import LLMService
from backend.services.alarm_service import AlarmService
from backend.core.db import SessionLocal
from backend.services.scheduler_monitor import monitor_job_async
from backend.core.logging_config import setup_global_logging

# Set up logging (Sensitive Data Masking enabled)
setup_global_logging(
    level=logging.INFO,
    log_file=os.path.join(PROJECT_ROOT, "logs/sync_prices_scheduler.log")
)
logger = logging.getLogger("sync_prices_scheduler")
KST = timezone("Asia/Seoul")

# Redundant notification logic moved to MarketDataService



async def run_sync_script(job_id: str = "market_sync"):
    """
    Directly calls MarketDataService for syncing prices and taking snapshots.
    """
    from backend.services.market_data import MarketDataService
    
    db = SessionLocal()
    async with monitor_job_async(job_id, db):
        logger.info(f"--- Starting Sync Job [{job_id}] at {datetime.now(KST)} ---")
        
        try:
            # 1. Sync All Prices
            ticker_count = MarketDataService.sync_all_prices(db)
            logger.info(f"Market prices synced successfully. Tickers: {ticker_count}")
            
            # 2. Take Portfolio Snapshot
            MarketDataService.take_portfolio_snapshot(db)
            logger.info("Portfolio snapshot captured successfully.")
            
            # 3. Creative Notification
            await MarketDataService.notify_sync_completion(ticker_count)
            
        except Exception as e:
            logger.error(f"Error during sync execution: {e}")
            raise e
        finally:
            db.close()
            logger.info(f"--- Sync Job [{job_id}] Finished at {datetime.now(KST)} ---")

async def run_alarm_processing():
    """
    Periodically processes pending alarms using the shared LLM model.
    """
    db = SessionLocal()
    async with monitor_job_async("alarm_processing", db):
        logger.info("--- Starting Alarm Processing Job ---")
        try:
            await AlarmService.process_pending_alarms(db)
            logger.info("Alarm processing completed successfully.")
        except Exception as e:
            logger.error(f"Alarm processing job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("--- Alarm Processing Job Finished ---")

async def run_backup_job():
    """
    Executes the database backup logic.
    """
    from backend.scripts.manage import backup_db
    from unittest.mock import MagicMock
    
    db = SessionLocal()
    async with monitor_job_async("daily_backup", db):
        logger.info("--- Starting DB Backup Job ---")
        try:
            # manage.py의 backup_db는 argparse args를 기대하므로 mock으로 감쌉니다.
            args = MagicMock()
            backup_db(args)
            logger.info("DB Backup completed successfully via Python service.")
        except Exception as e:
            logger.error(f"DB Backup job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("--- DB Backup Job Finished ---")

async def run_rate_change_check():
    """
    한국은행/미국 기준금리 변경 감지
    """
    from backend.services.economy.rate_alerts import check_rate_changes_and_notify

    db = SessionLocal()
    async with monitor_job_async("rate_change_check", db):
        logger.info("--- Starting Rate Change Check ---")
        try:
            changed = await check_rate_changes_and_notify()
            if changed:
                logger.info("Rate change alert sent.")
            else:
                logger.info("No rate changes detected.")
        except Exception as e:
            logger.error(f"Rate change check job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("--- Rate Change Check Finished ---")

async def run_monthly_maintenance():
    """
    매월 1일 수행되는 유지보수 작업 (스팸 리포트 및 데이터 정리)
    """
    db = SessionLocal()
    async with monitor_job_async("monthly_maintenance", db):
        logger.info("--- Starting Monthly Maintenance Job ---")
        try:
            from backend.services.maintenance import (
                generate_monthly_spam_report, 
                cleanup_old_spam_data,
                cleanup_old_news_data
            )
            
            # 1. 스팸 리포트 전송
            await generate_monthly_spam_report(db)
            
            # 2. 오래된 스팸 및 일반 뉴스 데이터 정리
            await cleanup_old_spam_data(db, months=1)
            await cleanup_old_news_data(db)
            
            logger.info("Monthly maintenance completed successfully.")
        except Exception as e:
            logger.error(f"Monthly maintenance job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("--- Monthly Maintenance Job Finished ---")

async def run_spam_retraining():
    """
    주간 스팸 분류 모델 재학습 (매주 일요일 새벽)
    """
    from backend.services.spam_trainer import train_spam_model
    
    db = SessionLocal()
    async with monitor_job_async("spam_retraining", db):
        logger.info("--- Starting Weekly Spam Model Retraining ---")
        try:
            # 훈련 수행 (임계치 미달 시 알아서 skip됨)
            success = train_spam_model()
            if success:
                logger.info("Spam model retrained and saved successfully.")
            else:
                logger.info("Spam model retraining skipped (not enough data or no changes).")
        except Exception as e:
            logger.error(f"Spam retraining job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("--- Weekly Spam Model Retraining Finished ---")

async def main():
    logger.info(f"Current System Time: {datetime.now(KST)}")
    
    # Explicitly use Asia/Seoul timezone for scheduler
    scheduler = AsyncIOScheduler(timezone=KST)
    
    # 1. KR Market Close: Mon-Fri 15:33 KST (5분 단위 알람 처리와 겹침 방지)
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='mon-fri', hour=15, minute=33, timezone=KST),
        id="kr_market_close",
        name="KR Market Close Sync (15:33 KST)",
        kwargs={"job_id": "kr_market_close"}
    )

    
    # 2. US Market Close: Tue-Sat 06:30 KST
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='tue-sat', hour=6, minute=30, timezone=KST),
        id="us_market_close",
        name="US Market Close Sync (06:30 KST)",
        kwargs={"job_id": "us_market_close"},
        misfire_grace_time=60  # 최대 60초까지 늦어도 실행
    )
    
    # 3. Alarm Processing: Every 5 minutes (07:00 - 21:59 KST)
    scheduler.add_job(
        run_alarm_processing,
        CronTrigger(hour='7-21', minute='*/5', timezone=KST),
        id="alarm_processing",
        name="Periodic Alarm Summary (Every 5 mins, 7am-10pm)"
    )

    # 4. Daily DB Backup: Every day at 06:30 KST
    scheduler.add_job(
        run_backup_job,
        CronTrigger(hour=6, minute=30, timezone=KST),
        id="daily_backup",
        name="Daily DB Backup (06:30 KST)"
    )

    # 4-1. Rate Change Check: Every day at 09:05 KST
    scheduler.add_job(
        run_rate_change_check,
        CronTrigger(hour=9, minute=5, timezone=KST),
        id="rate_change_check",
        name="Rate Change Check (09:05 KST)"
    )

    # 5. Monthly Maintenance: 1st day of every month at 04:00 KST (Cleanup) and 09:00 KST (Report)
    # 리포트는 보기 편하게 아침 9시에 전송
    scheduler.add_job(
        run_monthly_maintenance,
        CronTrigger(day=1, hour=9, minute=0, timezone=KST),
        id="monthly_maintenance",
        name="Monthly Spam Report & Cleanup (1st of Month)"
    )
    
    # 6. Weekly Spam Retraining: Every Sunday at 04:00 KST (도라 제안 💖)
    scheduler.add_job(
        run_spam_retraining,
        CronTrigger(day_of_week='sun', hour=4, minute=0, timezone=KST),
        id="spam_retraining",
        name="Weekly Spam Model Retraining (Sun 04:00 KST)"
    )
    
    logger.info("Starting Price Sync Scheduler...")
    scheduler.start()
    
    # 시작 알림 제거 (불필요)
    
    logger.info("Jobs scheduled:")
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        logger.info(f"  - {job.name} | Next run: {next_run}")
    
    try:
        # Keep the script running
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down Price Sync Scheduler...")
        scheduler.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
