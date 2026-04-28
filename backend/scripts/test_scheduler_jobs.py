from __future__ import annotations

from datetime import datetime

import pytest

from backend.core.db import SessionLocal
from backend.scripts.runners.run_sync_prices_scheduler import (
    run_alarm_processing,
    run_sync_script,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scheduler_jobs_run_once() -> None:
    db = SessionLocal()
    try:
        run_sync_script()
        await run_alarm_processing()
    finally:
        db.close()


if __name__ == "__main__":
    import asyncio

    print(f"[{datetime.now()}] Testing sync script...")
    asyncio.run(test_scheduler_jobs_run_once())
