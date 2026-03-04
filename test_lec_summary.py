import asyncio
import logging
import sys
import os

# backend 경로 추가
sys.path.append(os.path.join(os.getcwd(), "backend"))

from backend.services.news.esports_results import fetch_lec_results_summary

async def test_lec():
    logging.basicConfig(level=logging.INFO)
    print("Fetching LEC results summary...")
    summary = await fetch_lec_results_summary(limit=10, lookback_hours=48)
    print(f"Summary: '{summary}'")
    if not summary:
        print("Summary is empty (expected if no matches in last 48h)")

if __name__ == "__main__":
    asyncio.run(test_lec())
