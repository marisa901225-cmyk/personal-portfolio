from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from backend.core.config import settings
from backend.services.news.weather import _generate_weather_message, fetch_weather_forecast
from backend.services.news.weather_kma import (
    fetch_ultra_short_snapshot,
    get_base_time,
    get_base_times_ordered,
    get_ultra_base_times_ordered,
)

KST = ZoneInfo("Asia/Seoul")


async def fetch_actual_ultra_short_snapshot() -> None:
    service_key = settings.kma_service_key
    if not service_key:
        print("KMA_SERVICE_KEY not set in environment")
        return

    print("Fetching actual ultra-short forecast data for Seoul (60,127)...")
    data = await fetch_ultra_short_snapshot(service_key, nx=60, ny=127)
    if data:
        print(f"Weather Data: {data}")
        print(f"Base Time used: {data.get('fcst_date')} {data.get('fcst_time')}")
    else:
        print("Failed to fetch actual ultra-short forecast data.")


def inspect_kma_base_time_selection() -> None:
    now = datetime.now(KST)
    print(f"Current KST Time: {now}")
    print(f"Candidate times: {get_base_times_ordered()}")
    base_date, base_time = get_base_time()
    print(f"Selected Base Time: {base_date} {base_time}")


def inspect_kma_ultra_base_time_selection() -> None:
    simulated_now = datetime(2026, 2, 6, 15, 30, tzinfo=KST)
    with patch("backend.services.news.weather_kma.datetime") as mock_datetime:
        mock_datetime.now.return_value = simulated_now
        mock_datetime.replace = datetime.replace
        mock_datetime.strptime = datetime.strptime
        times = get_ultra_base_times_ordered(max_slots=5)
    print(f"Candidate ultra-short times for 15:30: {times}")


async def inspect_weather_briefing_time() -> None:
    msg_forecast = await _generate_weather_message(
        temp="-10",
        weather_status="맑음",
        base_date="20260209",
        base_time="0500",
        include_briefing_context=False,
        display_datetime=None,
    )
    print(f"Forecast-time message preview: {msg_forecast[:100]}")

    msg_now = await _generate_weather_message(
        temp="-10",
        weather_status="맑음",
        base_date="20260209",
        base_time="0500",
        include_briefing_context=False,
        display_datetime=datetime.now(KST).replace(hour=7, minute=0),
    )
    print(f"Briefing-time message preview: {msg_now[:100]}")


async def fetch_weather_forecast_demo() -> None:
    message = await fetch_weather_forecast()
    print(message[:200] + "..." if isinstance(message, str) and len(message) > 200 else message)


async def main() -> None:
    inspect_kma_base_time_selection()
    inspect_kma_ultra_base_time_selection()
    await inspect_weather_briefing_time()
    await fetch_weather_forecast_demo()
    await fetch_actual_ultra_short_snapshot()


if __name__ == "__main__":
    asyncio.run(main())
