import asyncio
import os
import sys
from datetime import datetime

# 프로젝트 루트를 패스에 추가
sys.path.append(os.getcwd())

from backend.scripts.run_sync_prices_scheduler import run_sync_script, run_alarm_processing
from backend.core.db import SessionLocal

async def test():
    print(f"[{datetime.now()}] Testing sync script...")
    # run_sync_script() is synchronous
    run_sync_script()
    print(f"[{datetime.now()}] Sync script test done.")

    print(f"[{datetime.now()}] Testing alarm processing...")
    db = SessionLocal()
    try:
        await run_alarm_processing()
    finally:
        db.close()
    print(f"[{datetime.now()}] Alarm processing test done.")

if __name__ == "__main__":
    asyncio.run(test())
