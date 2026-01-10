import asyncio
import logging
import os
import sys
import subprocess
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv("backend/.env")

# 프로젝트 루트를 패스에 추가 (backend 패키지 임포트용)
sys.path.append(os.getcwd())

from backend.services.llm_service import LLMService
from backend.services.alarm_service import AlarmService
from backend.core.db import SessionLocal

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("sync_prices_scheduler")

def send_telegram_sync(text: str):
    """
    시세 동기화 전용 텔레그램 전송 (기존 봇 토큰 사용)
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set for sync notify")
        return

    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        res = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        res.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to send telegram: {e}")

def generate_creative_msg(ticker_count: int):
    """
    LLM을 사용하여 창의적인 업데이트 메시지 생성
    """
    llm = LLMService.get_instance()
    if not llm.is_loaded():
        return f"💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 기준"

    prompt = f"""<start_of_turn>user
You are a witty and competent assistant synchronizing investment portfolio prices. You just finished updating {ticker_count} tickers.
[Rules]
1. Inform the user that the update is complete in Korean.
2. You MUST include the exact ticker count ({ticker_count}). Do not hallucinate numbers.
3. Use a polite and friendly tone in Korean, and be creative and varied in each response.
4. Keep it concise (2-3 sentences).
5. Use HTML tags (e.g., <b>, <i>) sparingly to style the Telegram message.
6. Start directly without introductory phrases.

Message (in Korean):<end_of_turn>
<start_of_turn>model
"""
    try:
        creative_text = llm.generate(prompt, max_tokens=256, temperature=0.8)
        # 종목 숫자가 환각으로 바뀌었을 경우를 방지하기 위해 강제로 재검증
        if str(ticker_count) not in creative_text:
            creative_text += f"\n\n(참고: 총 {ticker_count}개 종목 업데이트 완료)"
        
        # 하단에 시간 정보 추가
        sync_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        final_msg = f"{creative_text}\n\n🕒 {sync_time} 기준"
        return final_msg
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return f"💰 시세 업데이트 완료!\n- 총 {ticker_count}개 종목\n- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 기준"

def run_sync_script():
    """
    Executes the existing sync_prices.sh bash script.
    """
    script_path = os.path.join(os.path.dirname(__file__), "sync_prices.sh")
    logger.info(f"--- Starting Sync Job at {datetime.now()} ---")
    
    try:
        # Pass SKIP_TELEGRAM_NOTIFY=true to avoid double notifications
        env = os.environ.copy()
        env["SKIP_TELEGRAM_NOTIFY"] = "true"
        
        result = subprocess.run(
            ["bash", script_path],
            env=env,
            capture_output=True,
            text=True
        )
        
        ticker_count = 0
        if result.stdout:
            for line in result.stdout.strip().split('\n'):
                logger.info(f"[Script STDOUT] {line}")
                if "TICKER_COUNT=" in line:
                    try:
                        ticker_count = int(line.split("=")[1])
                    except:
                        pass

        if result.returncode == 0:
            logger.info(f"Sync script executed successfully. Tickers: {ticker_count}")
            # Generate and send creative message
            msg = generate_creative_msg(ticker_count)
            send_telegram_sync(msg)
        else:
            logger.error(f"Sync script failed with return code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split('\n'):
                    logger.error(f"[Script STDERR] {line}")
                    
    except Exception as e:
        logger.error(f"Error during sync script execution: {e}")
    finally:
        logger.info(f"--- Sync Job Finished at {datetime.now()} ---")

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

async def main():
    logger.info(f"Current System Time: {datetime.now()}")
    # Initialize LLM early
    try:
        LLMService.get_instance()
    except Exception as e:
        logger.error(f"Failed to initialize LLMService: {e}")

    scheduler = AsyncIOScheduler() # Uses local timezone
    
    # 1. KR Market Close: Mon-Fri 15:35
    # (Matches 06:35 UTC if the machine is on UTC, but we use timezone="Asia/Seoul")
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='mon-fri', hour=15, minute=35),
        id="kr_market_close",
        name="KR Market Close Sync (15:35 KST)"
    )
    
    # 2. US Market Close: Tue-Sat 06:30
    # (Matches 21:30 UTC day before if the machine is on UTC)
    scheduler.add_job(
        run_sync_script,
        CronTrigger(day_of_week='tue-sat', hour=6, minute=30),
        id="us_market_close",
        name="US Market Close Sync (06:30 KST)"
    )
    
    # 3. Alarm Processing: Every 5 minutes (07:00 - 21:59 KST)
    scheduler.add_job(
        run_alarm_processing,
        CronTrigger(hour='7-21', minute='*/5'),
        id="alarm_processing",
        name="Periodic Alarm Summary (Every 5 mins, 7am-10pm)"
    )
    
    logger.info("Starting Price Sync Scheduler...")
    scheduler.start()
    
    logger.info("Jobs scheduled:")
    for job in scheduler.get_jobs():
        next_run = getattr(job, 'next_run_time', 'Unknown')
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
