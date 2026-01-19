"""
통합 태스크 러너 스크립트

다양한 백엔드 유틸리티 작업을 하나의 스크립트로 실행할 수 있습니다.

사용법:
    python -m backend.scripts.runners.run_tasks --task alarms      # 알람 배치 처리
    python -m backend.scripts.runners.run_tasks --task telegram    # 텔레그램 명령어 등록
    python -m backend.scripts.runners.run_tasks --task news        # 뉴스 스케줄러 실행
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 프로젝트 루트를 패스에 추가
sys.path.append(os.getcwd())

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("run_tasks")


# ============================================================
# Task 1: Process Alarms (알람 배치 처리)
# ============================================================

async def task_process_alarms():
    """대기 중인 알람을 배치 처리합니다."""
    from backend.core.db import SessionLocal
    from backend.services.alarm_service import AlarmService
    
    logger.info("Starting alarm batch processing...")
    
    db = SessionLocal()
    try:
        await AlarmService.process_pending_alarms(db)
        logger.info("Batch processing completed successfully.")
    except Exception as e:
        logger.error(f"Error during batch processing: {e}")
        raise
    finally:
        db.close()


# ============================================================
# Task 2: Register Telegram Commands (텔레그램 명령어 등록)
# ============================================================

async def task_register_telegram():
    """텔레그램 봇 명령어를 등록합니다."""
    import httpx
    
    token = os.getenv("ALARM_TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("❌ ALARM_TELEGRAM_BOT_TOKEN not found in .env")
        return

    commands = [
        {"command": "report", "description": "리포트 생성 (예: /report 이번달, /report 스팀)"},
        {"command": "list", "description": "스팸 필터 규칙 목록 보기"},
        {"command": "add", "description": "스팸 필터 키워드 추가 (예: /add 키워드)"},
        {"command": "del", "description": "스팸 필터 규칙 삭제 (예: /del ID)"},
        {"command": "help", "description": "도움말 보기"}
    ]

    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"commands": commands})
            result = resp.json()
            if result.get("ok"):
                logger.info("✅ Telegram commands registered successfully!")
            else:
                logger.error(f"❌ Failed to register commands: {result}")
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        raise


# ============================================================
# Task 3: Run News Scheduler (뉴스 스케줄러 실행)
# ============================================================

async def task_run_news_scheduler():
    """뉴스 스케줄러를 시작하고 계속 실행합니다."""
    from backend.scheduler import start_scheduler, shutdown_scheduler
    
    logger.info('Starting news scheduler service...')
    start_scheduler()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        shutdown_scheduler()
        logger.info('News scheduler service stopped.')


# ============================================================
# Main Entry Point
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="통합 태스크 러너 - 다양한 백엔드 유틸리티 작업 실행"
    )
    parser.add_argument(
        "--task",
        choices=["alarms", "telegram", "news"],
        required=True,
        help="실행할 작업: alarms (알람 처리), telegram (텔레그램 명령어 등록), news (뉴스 스케줄러)"
    )
    return parser


async def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    
    try:
        if args.task == "alarms":
            await task_process_alarms()
        elif args.task == "telegram":
            await task_register_telegram()
        elif args.task == "news":
            await task_run_news_scheduler()
        
        return 0
    except Exception as e:
        logger.error(f"Task '{args.task}' failed: {e}")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        raise SystemExit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        raise SystemExit(0)
