import json
import logging
import os
import asyncio
from typing import Any, Dict, Optional, Tuple

from ...services.alarm.sanitizer import clean_exaone_tokens
from ...services.llm_service import LLMService
from ...services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)
_WEATHER_MESSAGE_MAX_CHARS = 3500


def format_datetime_korean(base_date: str, base_time: str) -> str:
    """발표일시를 한국어 형식으로 변환한다."""
    try:
        year = base_date[:4]
        month = base_date[4:6].lstrip("0")
        day = base_date[6:8].lstrip("0")
        hour = int(base_time[:2])

        if hour < 12:
            period = "오전"
            display_hour = hour if hour > 0 else 12
        else:
            period = "오후"
            display_hour = hour - 12 if hour > 12 else 12
        return f"{year}년 {month}월 {day}일 {period} {display_hour}시"
    except Exception as e:
        logger.error("Failed to format datetime: %s", e)
        return f"{base_date} {base_time}"


def get_fallback_message(
    temp: str,
    weather_status: str,
    pop: str,
    base_date: str,
    base_time: str,
    max_temp: str = "N/A",
) -> str:
    """LLM 실패 시 사용할 폴백 메시지를 생성한다."""
    fallback_path = os.path.join(os.path.dirname(__file__), "../../data/weather_fallback.json")
    try:
        if os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8") as f:
                template = json.load(f).get("weather_fallback", "")
            if template:
                return template.format(
                    temp=temp,
                    max_temp=max_temp,
                    weather_status=weather_status,
                    pop=pop,
                    base_date=base_date,
                    base_time=base_time,
                )
    except Exception as e:
        logger.error("Failed to load weather fallback JSON: %s", e)

    max_temp_line = ""
    if max_temp and max_temp != "N/A":
        max_temp_line = f"⬆️ <b>오늘 최고기온</b>: {max_temp}°C\n"

    return (
        f"<b>[오늘의 날씨 정보 - 서울]</b> 🌦️\n\n"
        f"🌡️ <b>기온</b>: {temp}°C\n"
        f"{max_temp_line}"
        f"☁️ <b>날씨</b>: {weather_status}\n"
        f"☔ <b>강수확률</b>: {pop}%\n\n"
        f"📅 <b>발표시각</b>: {base_date} {base_time}\n\n"
        f"날씨 확인하고 따뜻하게 입고 나가, LO! ❤️"
    )


def format_ultra_short_data(snapshot: Dict[str, str]) -> str:
    """초단기예보 스냅샷을 프롬프트용 단일 문자열로 변환한다."""
    if not snapshot:
        return "없음"

    parts = []
    weather_status = snapshot.get("weather_status")
    if weather_status:
        parts.append(f"하늘/강수: {weather_status}")
    if snapshot.get("temp"):
        parts.append(f"기온: {snapshot['temp']}°C")
    if snapshot.get("rn1"):
        parts.append(f"1시간 강수량: {snapshot['rn1']}mm")
    if snapshot.get("reh"):
        parts.append(f"습도: {snapshot['reh']}%")
    if snapshot.get("wsd"):
        parts.append(f"풍속: {snapshot['wsd']}m/s")

    fcst_date = snapshot.get("fcst_date", "")
    fcst_time = snapshot.get("fcst_time", "")
    if fcst_date and fcst_time:
        parts.append(f"예측시각: {format_datetime_korean(fcst_date, fcst_time)}")

    return " | ".join(parts) if parts else "없음"


async def fetch_briefing_context() -> Tuple[Optional[Any], Optional[Any], Optional[str], Optional[Dict]]:
    """모닝 브리핑용 부가 데이터(경제/미세먼지/LEC/선물옵션)를 병렬 수집한다."""
    economic_snapshot = None
    dust_alarm = None
    lec_results = None
    futures_options_data = None

    try:
        from ..economy.economy_service import EconomyService
        from ...integrations.air_korea.air_korea_client import air_korea_client
        from .esports_results import fetch_lec_results_summary
        from ...integrations.kis.kis_client import get_options_display_board, get_futures_daily_chart

        logger.info("Fetching economic, dust, LEC, and futures/options data for morning briefing...")
        
        # 날짜 설정
        from datetime import datetime
        from zoneinfo import ZoneInfo
        kst = ZoneInfo("Asia/Seoul")
        now = datetime.now(kst)
        maturity_month = now.strftime("%Y%m")
        
        econ_task = EconomyService.get_morning_snapshot() # 캐싱 로직은 EconomyService 내부 참고
        dust_task = air_korea_client.get_latest_active_alarm(district_name="서울")
        lec_task = fetch_lec_results_summary(limit=10, lookback_hours=48, max_chars=0)
        options_task = get_options_display_board(maturity_month)

        econ_result, dust_result, lec_result, options_result = await asyncio.gather(
            econ_task,
            dust_task,
            lec_task,
            options_task,
            return_exceptions=True,
        )

        if not isinstance(econ_result, Exception):
            economic_snapshot = econ_result
        if not isinstance(dust_result, Exception):
            dust_alarm = dust_result
        if not isinstance(lec_result, Exception):
            lec_results = lec_result
        if not isinstance(options_result, Exception):
            futures_options_data = options_result
            
    except Exception as e:
        logger.error("Failed to fetch additional data for morning briefing: %s", e)

    return economic_snapshot, dust_alarm, lec_results, futures_options_data


async def generate_weather_message_with_llm(
    temp: str,
    weather_status: str,
    pop: str,
    base_date: str,
    base_time: str,
    max_temp: str = "N/A",
    ultra_short_data: str = "없음",
    economic_snapshot: Optional[Any] = None,
    dust_alarm: Optional[Any] = None,
    lec_results: Optional[str] = None,
    futures_options_data: Optional[Dict] = None,
) -> str:
    """날씨 정보를 LLM으로 자연어 메시지로 변환한다."""
    def _trim_for_telegram(text: str, max_chars: int = _WEATHER_MESSAGE_MAX_CHARS) -> str:
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        cut_idx = max(truncated.rfind("\n"), truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
        if cut_idx >= 200:
            truncated = truncated[:cut_idx]
        return truncated.rstrip() + "\n\n... (이하 생략)"

    llm = LLMService.get_instance()
    if not llm.is_loaded():
        return get_fallback_message(
            temp=temp,
            weather_status=weather_status,
            pop=pop,
            base_date=base_date,
            base_time=base_time,
            max_temp=max_temp,
        )

    formatted_datetime = format_datetime_korean(base_date, base_time)

    econ_str = ""
    if economic_snapshot:
        try:
            from ..economy.economy_service import EconomyService

            econ_str = EconomyService.format_snapshot_for_llm(economic_snapshot)
        except Exception as e:
            logger.error("Failed to format economic data for LLM: %s", e)

    dust_str = ""
    if dust_alarm:
        try:
            item_name = "미세먼지" if dust_alarm.get("itemCode") == "PM10" else "초미세먼지"
            issue_gbn = dust_alarm.get("issueGbn", "주의보")
            issue_val = dust_alarm.get("issueVal", "N/A")
            district = dust_alarm.get("districtName", "서울")
            dust_str = f"현재 {district} 지역에 <b>{item_name} {issue_gbn}</b>가 발령 중이에요 (농도: {issue_val}ug/m3)."
        except Exception as e:
            logger.error("Failed to format dust alarm for LLM: %s", e)

    # 선물/옵션 데이터 포맷팅
    fo_str = "데이터 없음"
    if futures_options_data:
        try:
            calls = futures_options_data.get("output1", [])
            puts = futures_options_data.get("output2", [])
            total_call_ask = sum(int(c.get("total_askp_rsqn", 0)) for c in calls)
            total_call_bid = sum(int(c.get("total_bidp_rsqn", 0)) for c in calls)
            total_put_ask = sum(int(p.get("total_askp_rsqn", 0)) for p in puts)
            total_put_bid = sum(int(p.get("total_bidp_rsqn", 0)) for p in puts)
            total_call_oi_change = sum(int(c.get("otst_stpl_qty_icdc", 0)) for c in calls)
            total_put_oi_change = sum(int(p.get("otst_stpl_qty_icdc", 0)) for p in puts)
            
            fo_str = (
                f"콜옵션 매도잔량:{total_call_ask:,}, 매수잔량:{total_call_bid:,}, OI증감:{total_call_oi_change:+,} | "
                f"풋옵션 매도잔량:{total_put_ask:,}, 매수잔량:{total_put_bid:,}, OI증감:{total_put_oi_change:+,}"
            )
        except Exception as e:
            logger.error("Failed to format futures/options data for LLM: %s", e)

    prompt_content = load_prompt(
        "weather_message",
        temp=temp,
        today_max_temp=max_temp,
        weather_status=weather_status,
        pop=pop,
        base_date=base_date,
        base_time=base_time,
        formatted_datetime=formatted_datetime,
        ultra_short_data=(ultra_short_data or "없음"),
        economic_data=econ_str,
        dust_info=dust_str,
        lec_results=(lec_results or "없음"),
        futures_options_data=fo_str,
    )
    if not prompt_content:
        logger.warning("Weather prompt file not found, using fallback")
        return get_fallback_message(
            temp=temp,
            weather_status=weather_status,
            pop=pop,
            base_date=base_date,
            base_time=base_time,
            max_temp=max_temp,
        )

    messages = [{"role": "user", "content": prompt_content}]
    try:
        creative_text = llm.generate_chat(
            messages,
            max_tokens=4096,
            temperature=0.85,
            stop=["Ok,", "사용자가", "지시사항"],
        )
        creative_text = clean_exaone_tokens(creative_text).strip()
        if not creative_text or len(creative_text) < 20:
            logger.warning("LLM generated empty/short weather message, using fallback")
            return get_fallback_message(
                temp=temp,
                weather_status=weather_status,
                pop=pop,
                base_date=base_date,
                base_time=base_time,
                max_temp=max_temp,
            )
        return _trim_for_telegram(creative_text)
    except Exception as e:
        logger.error("LLM weather message generation failed: %s", e, exc_info=True)
        return get_fallback_message(
            temp=temp,
            weather_status=weather_status,
            pop=pop,
            base_date=base_date,
            base_time=base_time,
            max_temp=max_temp,
        )
