from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from backend.services.news import weather, weather_cache
from backend.services.news.weather_cache import WeatherData


KST = ZoneInfo("Asia/Seoul")


@pytest.mark.asyncio
async def test_weather_cache_prefers_latest_forecast_without_external_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(weather_cache, "CACHE_DIR", tmp_path)
    generate_message = AsyncMock(return_value="오전 7시 브리핑")
    monkeypatch.setattr(weather, "_generate_weather_message", generate_message)

    today = datetime.now(KST).strftime("%Y%m%d")
    for base_time, temp in (("0500", "-10"), ("0600", "-9")):
        weather_cache.save_weather_cache(
            WeatherData(
                message="",
                temp=temp,
                weather_status="맑음",
                pop="0",
                base_date=today,
                base_time=base_time,
                cached_at=datetime.now(KST).isoformat(),
            )
        )

    latest = weather_cache.load_weather_cache()
    assert latest is not None
    assert latest.base_time == "0600"

    message = await weather.fetch_weather_from_cache()

    assert message == "오전 7시 브리핑"
    generate_message.assert_awaited_once()
    assert generate_message.await_args.kwargs["base_time"] == "0600"
    assert generate_message.await_args.kwargs["display_datetime"] is not None
