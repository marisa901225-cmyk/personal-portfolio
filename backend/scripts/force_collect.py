import asyncio
import logging
from sqlalchemy.orm import sessionmaker
from backend.core.db import engine
from backend.services.news.esports import collect_pandascore_schedules

logging.basicConfig(level=logging.INFO)

async def main():
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        print("Starting manual PandaScore collection...")
        await collect_pandascore_schedules(db)
        print("Manual collection finished.")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
