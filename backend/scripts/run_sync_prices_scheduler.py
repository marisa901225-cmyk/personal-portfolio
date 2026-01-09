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
당신은 사용자의 투자 포트폴리오 시세 동기화를 정기적으로 수행하는 유능하고 위트 있는 비서 AI입니다.
방금 총 {ticker_count}개의 종목에 대한 시세 업데이트를 성공적으로 마쳤습니다.

[규칙]
1. 업데이트가 완료되었다는 사실을 사용자에게 알려주세요.
2. 종목 개수({ticker_count}개)는 반드시 정확하게 포함해야 합니다. (절대로 다른 숫자를 지어내지 마세요)
3. 말투는 정중하면서도 친근하고, 매번 다르게 창의적으로 작성해 주세요. 
4. 너무 길지 않게 2~3문장 내외로 작성해 주세요.
5. HTML 태그(<b>, <i> 등)를 적절히 섞어서 텔레그램 메시지처럼 꾸며주세요.

메시지:<end_of_turn>
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
