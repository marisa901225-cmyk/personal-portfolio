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

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(PROJECT_ROOT, "backend/logs/sync_prices_scheduler.log"), encoding='utf-8')
    ]
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
    try:
        llm = LLMService.get_instance()
        if not llm.is_loaded():
            return f"💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} 기준"

        prompt = f"""<start_of_turn>user
You synced {ticker_count} tickers. Inform user in casual Korean (반말). Include ticker count. Add fun/encouraging comment. 2-3 sentences. No HTML. Emojis OK. No intro.
<end_of_turn>
<start_of_turn>model
"""
        creative_text = llm.generate(prompt, max_tokens=256, temperature=0.8)
        if str(ticker_count) not in creative_text:
            creative_text += f"\n\n(참고: 총 {ticker_count}개 종목 업데이트 완료)"
        
        sync_time = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        return f"{creative_text}\n\n🕒 {sync_time} 기준"
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return f"💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')} 기준"

async def run_sync_script():
    """
    Executes the existing sync_prices.sh bash script asynchronously.
    """
    script_path = os.path.join(PROJECT_ROOT, "backend/scripts/sync_prices.sh")
    logger.info(f"--- Starting Sync Job at {datetime.now(KST)} ---")
    
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
                    
    except Exception as e:
        logger.error(f"Error during sync script execution: {e}")
    finally:
        logger.info(f"--- Sync Job Finished at {datetime.now(KST)} ---")

async def run_alarm_processing():
    """
    Periodically processes pending alarms using the shared LLM model.
    """
    logger.info("--- Starting Alarm Processing Job ---")
    db = SessionLocal()
    try:
        await AlarmService.process_pending_alarms(db)
        logger.info("Alarm processing completed successfully.")
    except Exception as e:
        logger.error(f"Alarm processing job failed: {e}")
    finally:
        db.close()
        logger.info("--- Alarm Processing Job Finished ---")

async def run_backup_job():
    """
    Executes the database backup script.
    """
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
    except Exception as e:
        logger.error(f"DB Backup job failed: {e}")
    finally:
        logger.info("--- DB Backup Job Finished ---")

async def main():
    logger.info(f"Current System Time: {datetime.now(KST)}")
    
    # Initialize LLM early
    try:
        LLMService.get_instance()
        logger.info("LLMService initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize LLMService: {e}")

    # Explicitly use Asia/Seoul timezone for scheduler
    scheduler = AsyncIOScheduler(timezone=KST)
    
    # 1. KR Market Close: Mon-Fri 15:35 KST
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='mon-fri', hour=15, minute=35, timezone=KST),
        id="kr_market_close",
        name="KR Market Close Sync (15:35 KST)"
    )

    
    # 2. US Market Close: Tue-Sat 06:30 KST
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='tue-sat', hour=6, minute=30, timezone=KST),
        id="us_market_close",
        name="US Market Close Sync (06:30 KST)"
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

