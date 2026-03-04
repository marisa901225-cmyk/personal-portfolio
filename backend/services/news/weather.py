import logging
import asyncio
from datetime import datetime
from typing import Dict, Optional
from zoneinfo import ZoneInfo

from ...core.config import settings
from ...integrations.telegram import send_telegram_message
from .weather_cache import (
    WeatherData,
    clear_old_caches,
    is_cache_fresh,
    load_last_success_cache,
    load_weather_cache,
    save_last_success_cache,
    save_weather_cache,
)
from .weather_kma import (
    KMA_API_URL,
    KMA_ULTRA_API_URL,
    SEOUL_NX,
    SEOUL_NY,
    fetch_short_term_weather,
    fetch_ultra_short_snapshot,
    get_base_time,
    get_base_times_ordered,
    get_pty_status,
    get_sky_status,
    get_ultra_base_times_ordered,
)
from .weather_message import (
    fetch_briefing_context,
    format_datetime_korean,
    format_ultra_short_data,
    generate_weather_message_with_llm,
)

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


async def _fetch_ultra_short_snapshot() -> Dict[str, str]:
    """하위 호환성을 위한 초단기예보 조회 래퍼."""
    service_key = settings.kma_service_key
    if not service_key:
        return {}
    return await fetch_ultra_short_snapshot(service_key, nx=SEOUL_NX, ny=SEOUL_NY)


def _format_ultra_short_data(snapshot: Dict[str, str]) -> str:
    """하위 호환성을 위한 초단기예보 포맷 래퍼."""
    return format_ultra_short_data(snapshot)


async def _generate_weather_message(
    *,
    temp: str,
    max_temp: str = "N/A",
    rn1: str = "",
    reh: str = "",
    wsd: str = "",
    pop: str = "N/A",
    weather_status: str,
    base_date: str,
    base_time: str,
    include_briefing_context: bool = True,
    display_datetime: Optional[datetime] = None,
) -> str:
    """수집된 원천 데이터로 최종 브리핑 메시지를 생성한다."""
    economic_snapshot = None
    dust_alarm = None
    lec_results = None
    futures_options_data = None
    ultra_short_data = f"기온: {temp}°C | 하늘/강수: {weather_status} | 1시간 강수량: {rn1}mm | 습도: {reh}% | 풍속: {wsd}m/s"

    if include_briefing_context:
        economic_snapshot, dust_alarm, lec_results, futures_options_data = await fetch_briefing_context()

    # display_datetime이 있으면 해당 시간을 메시지 제목/표기용으로 사용
    # 없으면 base_date/base_time (예보 기준시각) 사용
    msg_date = display_datetime.strftime("%Y%m%d") if display_datetime else base_date
    msg_time = display_datetime.strftime("%H%M") if display_datetime else base_time

    return await generate_weather_message_with_llm(
        temp=temp,
        max_temp=max_temp,
        weather_status=weather_status,
        pop=pop,  # 전달받은 강수확률 사용
        base_date=msg_date,
        base_time=msg_time,
        ultra_short_data=ultra_short_data,
        economic_snapshot=economic_snapshot,
        dust_alarm=dust_alarm,
        lec_results=lec_results,
        futures_options_data=futures_options_data,
    )


async def _fetch_from_api(
    *,
    generate_message: bool = True,
    include_briefing_context: bool = True,
) -> Optional[WeatherData]:
    """기상청 API를 호출해 WeatherData를 구성한다."""
    service_key = settings.kma_service_key
    if not service_key:
        logger.warning("KMA_SERVICE_KEY not set.")
        return None

    # 초단기예보(실시간) + 단기예보(최고기온용) 병렬 호출
    ultra_task = fetch_ultra_short_snapshot(service_key, nx=SEOUL_NX, ny=SEOUL_NY)
    short_task = fetch_short_term_weather(service_key, nx=SEOUL_NX, ny=SEOUL_NY, max_slots=12)

    ultra_payload, short_payload = await asyncio.gather(ultra_task, short_task)

    if not ultra_payload:
        logger.warning("Ultra short forecast return no data.")
        return None

    max_temp = short_payload.get("max_temp", "N/A") if short_payload else "N/A"

    message = ""
    if generate_message:
        message = await _generate_weather_message(
            temp=ultra_payload.get("temp", "N/A"),
            max_temp=max_temp,
            rn1=ultra_payload.get("rn1", "0"),
            reh=ultra_payload.get("reh", "0"),
            wsd=ultra_payload.get("wsd", "0"),
            pop=short_payload.get("pop", "N/A") if short_payload else "N/A",
            weather_status=ultra_payload.get("weather_status", "알 수 없음"),
            base_date=ultra_payload.get("fcst_date", ""),
            base_time=ultra_payload.get("fcst_time", ""),
            include_briefing_context=include_briefing_context,
        )

    return WeatherData(
        message=message,
        temp=ultra_payload.get("temp", "N/A"),
        max_temp=max_temp,
        weather_status=ultra_payload.get("weather_status", "알 수 없음"),
        pop=short_payload.get("pop", "N/A") if short_payload else "N/A",
        base_date=ultra_payload.get("fcst_date", ""),
        base_time=ultra_payload.get("fcst_time", ""),
        cached_at=datetime.now(KST).isoformat(),
    )


async def prefetch_weather_at_05() -> None:
    """05시-06시 프리페치: 가용한 가장 최신 원천 데이터를 수집하여 캐시한다."""
    retry_delays = [0, 13 * 60, 20 * 60, 35 * 60]  # 05:12, 05:25, 05:45, 06:20 대략적 시점

    last_base_time = None
    
    # 이전에 저장된 최신 캐시가 있는지 확인
    existing_cache = load_weather_cache()
    if existing_cache:
        last_base_time = existing_cache.base_time
        logger.info("Found existing cache with base_time: %s", last_base_time)

    for attempt, delay in enumerate(retry_delays, 1):
        if delay > 0:
            logger.info("Prefetch attempt %s/%s after %s minutes...", attempt, len(retry_delays), delay // 60)
            await asyncio.sleep(delay)
        else:
            logger.info("Starting weather prefetch sequence...")

        try:
            # generate_message=False로 원천 데이터만 수집
            weather_data = await _fetch_from_api(generate_message=False, include_briefing_context=False)
            
            if weather_data:
                # 현재 수집된 데이터가 기존 캐시보다 더 최신이거나, 캐시가 없는 경우에만 저장
                if last_base_time is None or weather_data.base_time > last_base_time:
                    save_weather_cache(weather_data)
                    last_base_time = weather_data.base_time
                    logger.info("Prefetch successful on attempt %s. Cache updated to base_time: %s", attempt, last_base_time)
                    clear_old_caches()
                else:
                    logger.info("Attempt %s: Collected data (base_time: %s) is not newer than existing cache (%s).", 
                                attempt, weather_data.base_time, last_base_time)
            else:
                logger.warning("Prefetch attempt %s returned no data", attempt)
        except Exception as e:
            logger.error("Prefetch attempt %s failed: %s", attempt, e, exc_info=True)

    logger.info("Weather prefetch sequence finished. Latest base_time: %s", last_base_time)


async def fetch_weather_from_cache() -> Optional[str]:
    """오늘 날짜 최신 캐시 우선으로 날씨 메시지를 반환한다."""
    if is_cache_fresh():
        cached_data = load_weather_cache()
        if cached_data:
            if cached_data.message and cached_data.message.strip():
                logger.info("Using cached weather data from %s", cached_data.base_time)
                return cached_data.message

            logger.info("Fresh weather cache found without message. Generating at briefing time...")
            # 7시 브리핑 시점에 메시지를 생성하므로, 현재 시간(KST)을 표시용으로 전달
            now = datetime.now(KST)
            cached_data.message = await _generate_weather_message(
                temp=cached_data.temp,
                max_temp=cached_data.max_temp,
                weather_status=cached_data.weather_status,
                pop=cached_data.pop,
                base_date=cached_data.base_date,
                base_time=cached_data.base_time,
                include_briefing_context=True,
                display_datetime=now,
            )
            save_weather_cache(cached_data)
            return cached_data.message

    logger.warning("No fresh cache found. Trying immediate API call...")
    try:
        weather_data = await _fetch_from_api(generate_message=True, include_briefing_context=True)
        if weather_data:
            save_weather_cache(weather_data)
            logger.info("Immediate API call succeeded. Cache saved.")
            return weather_data.message
    except Exception as e:
        logger.error("Immediate API call failed: %s", e, exc_info=True)

    logger.warning("Immediate API call failed. Using last success cache...")
    last_success = load_last_success_cache()
    if not last_success:
        logger.error("No cache available (fresh or last_success). Cannot send weather notification.")
        return None

    if not (last_success.message and last_success.message.strip()):
        logger.warning("Last success cache has empty message. Regenerating now...")
        last_success.message = await _generate_weather_message(
            temp=last_success.temp,
            max_temp=last_success.max_temp,
            weather_status=last_success.weather_status,
            pop=last_success.pop,
            base_date=last_success.base_date,
            base_time=last_success.base_time,
            include_briefing_context=True,
        )
        save_last_success_cache(last_success)

    warning_prefix = "⚠️ <b>[이전 날씨 데이터]</b>\n\n"
    logger.info("Using last success cache from %s %s", last_success.base_date, last_success.base_time)
    return warning_prefix + last_success.message


async def fetch_weather_forecast() -> Optional[str]:
    """기상청 단기예보 API를 호출해 메시지를 반환한다 (하위 호환)."""
    weather_data = await _fetch_from_api(generate_message=True, include_briefing_context=True)
    return weather_data.message if weather_data else None


async def send_weather_notification() -> None:
    """날씨 정보를 텔레그램으로 전송한다."""
    message = await fetch_weather_from_cache()
    if message:
        await send_telegram_message(message)
        logger.info("Weather notification sent successfully.")
    else:
        logger.warning("Weather notification was empty, nothing sent.")


if __name__ == "__main__":
    import asyncio
    import logging

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    async def test():
        print("Testing KMA Short-term Forecast API...")
        msg = await fetch_weather_forecast()

        # LLM 라우팅 정보 출력
        from ...services.llm_service import LLMService
        llm = LLMService.get_instance()
        print(f"\n{'='*50}")
        print(f"[LLM Route]     {llm.last_route()}")
        print(f"[Used Paid?]    {llm.last_used_paid()}")
        print(f"[Current Model] {llm.get_current_model()}")
        print(f"[Settings Model]  remote_configured={llm.settings.is_remote_configured()}, paid_configured={llm.settings.is_paid_configured()}")
        print(f"[AI Report Model] {llm.settings.ai_report_model}")
        print(f"[Fallback Model]  {llm.settings.ai_report_fallback_model}")
        print(f"[AI Report URL]   {llm.settings.ai_report_base_url}")
        print(f"[LLM Base URL]    {llm.settings.llm_base_url}")
        print(f"[Last Error]    {llm.get_last_error()}")
        print(f"{'='*50}\n")

        print("-" * 50)
        print(msg if msg else "Failed to get weather message.")
        print("-" * 50)

    asyncio.run(test())
