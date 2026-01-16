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
    
    # 필터 최소화: 오늘부터 향후 30일간 모든 경기
    start_utc = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    
    params = {
        "filter[videogame]": "league-of-legends",
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
            
            if "LCK" in league_name.upper() or "CHALLENGERS" in league_name.upper() or "KOREA" in league_name.upper():
                print(f"[{video_game}] {league_name} | {match_name} | {begin_at}")
            else:
                # 다른 리그도 뭐가 있는지 확인 (일부만)
                if m.get("id") % 10 == 0:
                    print(f"--- Other: {league_name} | {match_name}")

if __name__ == "__main__":
    asyncio.run(check_lck_schedules())
