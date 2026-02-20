#!/usr/bin/env python3
"""
Manual test script for global /matches/running API.
"""
import asyncio
import logging
import json
from backend.services.news.esports_monitor import EsportsMonitor
from backend.core.db import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_global_running():
    print("Testing global /matches/running API...")
    monitor = EsportsMonitor(dry_run=True)
    
    try:
        # Initialize client if needed (though _fetch does it)
        matches = await monitor._fetch_running_matches()
        
        print(f"\n[Result] Found {len(matches)} running matches for enabled games.")
        
        for m in matches:
            game = m.get("_videogame")
            name = m.get("name")
            match_id = m.get("id")
            print(f"- [{game}] {name} (ID: {match_id})")
            
        if not matches:
            print("No matches currently running for enabled games (LoL, Valorant).")
            print("Checking raw API response to confirm endpoint works...")
            raw = await monitor._fetch("/matches/running", {"per_page": 5})
            print(f"Raw API returned {len(raw)} total matches across all games.")
            if raw:
                first = raw[0]
                print(f"First raw match: [{first.get('videogame', {}).get('slug')}] {first.get('name')}")

    except Exception as e:
        logger.error(f"Test failed: {e}")
    finally:
        if monitor._client:
            await monitor._client.aclose()

if __name__ == "__main__":
    asyncio.run(test_global_running())
