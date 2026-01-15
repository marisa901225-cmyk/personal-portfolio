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
    log_file=os.path.join(PROJECT_ROOT, "backend/logs/sync_prices_scheduler.log")
)
logger = logging.getLogger("sync_prices_scheduler")
KST = timezone("Asia/Seoul")

def send_telegram_sync(text: str):
    """
    시세 동기화 전용 텔레그램 전송 (기존 봇 토큰 사용 - DB 백업 봇)
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set for sync notify")
        return

    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        res.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to send telegram: {e}")

async def generate_creative_msg(ticker_count: int):
    """
    LLM을 사용하여 창의적인 업데이트 메시지 생성
    """
    from backend.services.prompt_loader import load_prompt
    
    try:
        llm = LLMService.get_instance()
        if not llm.is_loaded():
            return f"💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} 기준"

        # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
        prompt_content = load_prompt("sync_prices", ticker_count=ticker_count)
        if not prompt_content:
            # 폴백: 파일이 없으면 기본 메시지
            return f"💰 {ticker_count}개 종목 시세 업데이트 완료!"
        
        messages = [
            {
                "role": "user",
                "content": prompt_content
            }
        ]
        creative_text = llm.generate_chat(messages, max_tokens=128, temperature=0.8)
        if str(ticker_count) not in creative_text:
            creative_text += f"\n\n(참고: 총 {ticker_count}개 종목 업데이트 완료)"
        
        sync_time = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        return f"{creative_text}\n\n🕒 {sync_time} 기준"
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return f"💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} 기준"



async def run_sync_script(job_id: str = "market_sync"):
    """
    Executes the existing sync_prices.sh bash script asynchronously.
    """
    db = SessionLocal()
    async with monitor_job_async(job_id, db):
        script_path = os.path.join(PROJECT_ROOT, "backend/scripts/sync_prices.sh")
        logger.info(f"--- Starting Sync Job [{job_id}] at {datetime.now(KST)} ---")
        
        try:
            env = os.environ.copy()
            env["SKIP_TELEGRAM_NOTIFY"] = "true"
            # PYTHONPATH를 ROOT로 설정하여 스크립트 내부에서 backend 모듈 호출 원활하게 함
            env["PYTHONPATH"] = PROJECT_ROOT
            
            process = await asyncio.create_subprocess_exec(
                "bash", script_path,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            ticker_count = 0
            if stdout:
                lines = stdout.decode('utf-8', errors='ignore').strip().split('\n')
                for line in lines:
                    logger.info(f"[Script STDOUT] {line}")
                    if "TICKER_COUNT=" in line:
                        try:
                            ticker_count = int(line.split("=")[1])
                        except:
                            pass

            if stderr:
                lines = stderr.decode('utf-8', errors='ignore').strip().split('\n')
                for line in lines:
                    logger.error(f"[Script STDERR] {line}")

            if process.returncode == 0:
                logger.info(f"Sync script executed successfully. Tickers: {ticker_count}")
                msg = await generate_creative_msg(ticker_count)
                send_telegram_sync(msg)
            else:
                logger.error(f"Sync script failed with return code {process.returncode}")
                raise Exception(f"Sync script failed with return code {process.returncode}")
                        
        except Exception as e:
            logger.error(f"Error during sync script execution: {e}")
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
    Executes the database backup script.
    """
    db = SessionLocal()
    async with monitor_job_async("daily_backup", db):
        script_path = os.path.join(PROJECT_ROOT, "backend/scripts/backup_db.sh")
        logger.info("--- Starting DB Backup Job ---")
        try:
            process = await asyncio.create_subprocess_exec(
                "bash", script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if stdout:
                for line in stdout.decode().strip().split('\n'):
                    logger.info(f"[Backup STDOUT] {line}")
            if stderr:
                for line in stderr.decode().strip().split('\n'):
                    logger.error(f"[Backup STDERR] {line}")
                    
            if process.returncode == 0:
                logger.info("DB Backup completed successfully.")
            else:
                logger.error(f"DB Backup failed with return code {process.returncode}")
                raise Exception(f"Backup failed with return code {process.returncode}")
        except Exception as e:
            logger.error(f"DB Backup job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("--- DB Backup Job Finished ---")

async def run_monthly_maintenance():
    """
    매월 1일 수행되는 유지보수 작업 (스팸 리포트 및 데이터 정리)
    """
    db = SessionLocal()
    async with monitor_job_async("monthly_maintenance", db):
        logger.info("--- Starting Monthly Maintenance Job ---")
        try:
            from backend.services.maintenance import generate_monthly_spam_report, cleanup_old_spam_data
            
            # 1. 스팸 리포트 전송
            await generate_monthly_spam_report(db)
            
            # 2. 오래된 스팸 데이터 정리 (3개월 기준)
            await cleanup_old_spam_data(db, months=3)
            
            logger.info("Monthly maintenance completed successfully.")
        except Exception as e:
            logger.error(f"Monthly maintenance job failed: {e}")
            raise e
        finally:
            db.close()
            logger.info("--- Monthly Maintenance Job Finished ---")

async def main():
    logger.info(f"Current System Time: {datetime.now(KST)}")
    
    # Explicitly use Asia/Seoul timezone for scheduler
    scheduler = AsyncIOScheduler(timezone=KST)
    
    # 1. KR Market Close: Mon-Fri 15:35 KST
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='mon-fri', hour=15, minute=35, timezone=KST),
        id="kr_market_close",
        name="KR Market Close Sync (15:35 KST)",
        kwargs={"job_id": "kr_market_close"}
    )

    
    # 2. US Market Close: Tue-Sat 06:30 KST
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='tue-sat', hour=6, minute=30, timezone=KST),
        id="us_market_close",
        name="US Market Close Sync (06:30 KST)",
        kwargs={"job_id": "us_market_close"}
    )
    
    # 3. Alarm Processing: Every 5 minutes (07:00 - 21:59 KST)
    scheduler.add_job(
        run_alarm_processing,
        CronTrigger(hour='7-21', minute='*/5', timezone=KST),
        id="alarm_processing",
        name="Periodic Alarm Summary (Every 5 mins, 7am-10pm)"
    )

    # 4. Daily DB Backup: Every day at 03:00 KST
    scheduler.add_job(
        run_backup_job,
        CronTrigger(hour=3, minute=0, timezone=KST),
        id="daily_backup",
        name="Daily DB Backup (03:00 KST)"
    )

    # 5. Monthly Maintenance: 1st day of every month at 04:00 KST (Cleanup) and 09:00 KST (Report)
    # 리포트는 보기 편하게 아침 9시에 전송
    scheduler.add_job(
        run_monthly_maintenance,
        CronTrigger(day=1, hour=9, minute=0, timezone=KST),
        id="monthly_maintenance",
        name="Monthly Spam Report & Cleanup (1st of Month)"
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
