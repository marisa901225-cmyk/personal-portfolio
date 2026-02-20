#!/usr/bin/env python3
"""
Force collect esports schedules using the EsportsMonitor's indexer.
"""
import asyncio
import logging
from sqlalchemy.orm import sessionmaker
from backend.core.db import engine
from backend.services.news.esports_monitor import EsportsMonitor

logging.basicConfig(level=logging.INFO)

async def main():
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        print("Starting manual esports schedule indexing via EsportsMonitor...")
        monitor = EsportsMonitor(dry_run=True)
        # Initialize API client
        if not monitor.api_key:
            print("Error: PANDASCORE_API_KEY not set.")
            return
        await monitor._index_upcoming_matches(db)
        print("Manual indexing finished.")
    finally:
        if monitor._client:
            await monitor._client.aclose()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
