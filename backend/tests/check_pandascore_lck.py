import os
import httpx
import asyncio
from datetime import datetime, timedelta

async def check_lck_schedules():
    api_key = os.getenv("PANDASCORE_API_KEY")
    if not api_key:
        print("PANDASCORE_API_KEY not set.")
        return

    url = "https://api.pandascore.co/matches"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # 1월 15일부터 향후 7일간
    start_utc = "2026-01-15T00:00:00Z"
    end_utc = "2026-01-22T23:59:59Z"
    
    params = {
        "range[begin_at]": f"{start_utc},{end_utc}",
        "sort": "begin_at",
        "per_page": 100
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params)
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            print(response.text)
            return
            
        matches = response.json()
        print(f"Total matches found: {len(matches)}\n")
        
        for m in matches:
            league_name = m.get("league", {}).get("name")
            match_name = m.get("name")
            begin_at = m.get("begin_at")
            video_game = m.get("videogame", {}).get("name")
            
            if "LCK" in league_name.upper() or "CHALLENGERS" in league_name.upper():
                print(f"[{video_game}] {league_name} | {match_name} | {begin_at}")

if __name__ == "__main__":
    asyncio.run(check_lck_schedules())
