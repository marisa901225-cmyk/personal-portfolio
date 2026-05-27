from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import requests

from backend.integrations.kis.kis_client import get_futures_daily_chart, get_futures_period_price
from backend.services.economy.kr_weekly_sentiment import (
    analyze_kr_weekly_sentiment,
    format_kr_weekly_sentiment_report,
)

KST = ZoneInfo("Asia/Seoul")


async def fetch_futures_period_price_demo() -> None:
    now = datetime.now(KST)
    start = (now - timedelta(days=60)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    data = await get_futures_period_price("101000", start, end)
    print(f"Period price keys: {list(data.keys()) if data else 'no response'}")


async def fetch_futures_period_price_v2_demo() -> None:
    now = datetime.now(KST)
    start = (now - timedelta(days=60)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    data = await get_futures_period_price("101000", start, end)
    print(f"[V2] Period price keys: {list(data.keys()) if data else 'no response'}")


async def fetch_futures_daily_chart_demo() -> None:
    now = datetime.now(KST)
    start = (now - timedelta(days=60)).strftime("%Y%m%d")
    end = now.strftime("%Y%m%d")
    data = await get_futures_daily_chart("101000", start, end)
    history = data.get("output2", []) if data else []
    print(f"Daily chart rows: {len(history)}")


async def inspect_weekly_futures_sentiment_demo() -> None:
    result = await analyze_kr_weekly_sentiment(
        futures_symbol="101000",
        lookback_days=45,
        lookback_bars=5,
    )
    print(format_kr_weekly_sentiment_report(result))
    print(json.dumps(result, ensure_ascii=False, indent=2))


async def check_pandascore_lck_schedule_demo() -> None:
    api_key = os.getenv("PANDASCORE_API_KEY")
    if not api_key:
        print("PANDASCORE_API_KEY not set.")
        return

    params = {
        "range[begin_at]": "2026-01-15T00:00:00Z,2026-01-22T23:59:59Z",
        "sort": "begin_at",
        "per_page": 100,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.pandascore.co/matches", headers=headers, params=params)
        response.raise_for_status()
        matches = response.json()
        lck_matches = [
            match
            for match in matches
            if "LCK" in match.get("league", {}).get("name", "").upper()
            or "CHALLENGERS" in match.get("league", {}).get("name", "").upper()
        ]
        print(f"Matched LCK/LCK CL schedules: {len(lck_matches)}")


async def check_pandascore_lol_feed_demo() -> None:
    api_key = os.getenv("PANDASCORE_API_KEY")
    if not api_key:
        print("PANDASCORE_API_KEY not set.")
        return

    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "filter[videogame]": "league-of-legends",
        "sort": "begin_at",
        "per_page": 100,
    }

    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.pandascore.co/matches", headers=headers, params=params)
        response.raise_for_status()
        matches = response.json()
        print(f"Total LoL matches found: {len(matches)}")


def check_direct_chat_completion_server() -> None:
    try:
        requests.get("http://127.0.0.1:8080/health", timeout=1.0).raise_for_status()
    except requests.RequestException as exc:
        print(f"Local chat completion server is not reachable: {exc}")
        return

    payload = {
        "model": "model",
        "messages": [{"role": "user", "content": "spam? [광고] 포인트!"}],
        "max_tokens": 10,
    }
    response = requests.post("http://127.0.0.1:8080/v1/chat/completions", json=payload, timeout=10.0)
    response.raise_for_status()
    print(response.json())


async def main() -> None:
    check_direct_chat_completion_server()
    await fetch_futures_daily_chart_demo()
    await fetch_futures_period_price_demo()
    await fetch_futures_period_price_v2_demo()
    await inspect_weekly_futures_sentiment_demo()
    await check_pandascore_lck_schedule_demo()
    await check_pandascore_lol_feed_demo()


if __name__ == "__main__":
    asyncio.run(main())
