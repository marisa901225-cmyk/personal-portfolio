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
        from ..economy.kr_derivatives_weekly_briefing import get_latest_option_snapshot_summary
        from ...integrations.air_korea.air_korea_client import air_korea_client
        from .esports_results import fetch_lec_results_summary

        logger.info("Fetching economic, dust, LEC, and futures/options snapshot data for morning briefing...")

        econ_task = EconomyService.get_morning_snapshot()  # 캐싱 로직은 EconomyService 내부 참고
        dust_task = air_korea_client.get_latest_active_alarm(district_name="서울")
        lec_task = fetch_lec_results_summary(limit=10, lookback_hours=48, max_chars=0)
        options_task = asyncio.to_thread(get_latest_option_snapshot_summary)

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
    def _load_persona_config() -> Tuple[str, str]:
        config_path = os.path.join(os.path.dirname(__file__), "../../data/persona_config.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                active = config.get("active_persona", "애니 (Annie)")
                # personas 딕셔너리가 없거나 해당 캐릭터가 없어도 이름은 active로 사용
                persona_data = config.get("personas", {}).get(active, {})
                setting = persona_data.get("setting", "")  # 설정이 없으면 빈 문자열
                return active, setting
        except Exception as e:
            logger.error("Failed to load persona config: %s", e)
        return "애니 (Annie)", ""

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
            def _to_int(value: Any) -> int:
                try:
                    return int(float(str(value).replace(",", "").strip()))
                except (TypeError, ValueError):
                    return 0

            def _to_float(value: Any) -> float:
                try:
                    return float(str(value).replace(",", "").strip())
                except (TypeError, ValueError):
                    return 0.0

            # 1) 주간 파생용 스냅샷 캐시 포맷(권장 경로)
            if "call_bid_total" in futures_options_data and "put_bid_total" in futures_options_data:
                total_call_ask = _to_int(futures_options_data.get("call_ask_total"))
                total_call_bid = _to_int(futures_options_data.get("call_bid_total"))
                total_put_ask = _to_int(futures_options_data.get("put_ask_total"))
                total_put_bid = _to_int(futures_options_data.get("put_bid_total"))
                total_call_oi_change = _to_int(futures_options_data.get("call_oi_change_total"))
                total_put_oi_change = _to_int(futures_options_data.get("put_oi_change_total"))
                pcr = _to_float(futures_options_data.get("put_call_bid_ratio"))
                trading_date = str(futures_options_data.get("trading_date") or "")
                if len(trading_date) == 8:
                    trading_date = f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:8]}"

                fo_str = (
                    f"{trading_date} 장마감 스냅샷 | "
                    f"콜옵션 매도잔량:{total_call_ask:,}, 매수잔량:{total_call_bid:,}, OI증감:{total_call_oi_change:+,} | "
                    f"풋옵션 매도잔량:{total_put_ask:,}, 매수잔량:{total_put_bid:,}, OI증감:{total_put_oi_change:+,} | "
                    f"Put/Call(매수잔량):{pcr:.2f}"
                )
            # 2) (하위호환) 실시간 옵션 전광판 raw payload 포맷
            else:
                calls = futures_options_data.get("output1", [])
                puts = futures_options_data.get("output2", [])
                total_call_ask = sum(_to_int(c.get("total_askp_rsqn")) for c in calls if isinstance(c, dict))
                total_call_bid = sum(_to_int(c.get("total_bidp_rsqn")) for c in calls if isinstance(c, dict))
                total_put_ask = sum(_to_int(p.get("total_askp_rsqn")) for p in puts if isinstance(p, dict))
                total_put_bid = sum(_to_int(p.get("total_bidp_rsqn")) for p in puts if isinstance(p, dict))
                total_call_oi_change = sum(_to_int(c.get("otst_stpl_qty_icdc")) for c in calls if isinstance(c, dict))
                total_put_oi_change = sum(_to_int(p.get("otst_stpl_qty_icdc")) for p in puts if isinstance(p, dict))

                fo_str = (
                    f"콜옵션 매도잔량:{total_call_ask:,}, 매수잔량:{total_call_bid:,}, OI증감:{total_call_oi_change:+,} | "
                    f"풋옵션 매도잔량:{total_put_ask:,}, 매수잔량:{total_put_bid:,}, OI증감:{total_put_oi_change:+,}"
                )
        except Exception as e:
            logger.error("Failed to format futures/options data for LLM: %s", e)

    # 페르소나 설정 로드
    persona_name, persona_setting = _load_persona_config()

    prompt_content = load_prompt(
        "weather_message",
        persona=persona_name,
        persona_setting=persona_setting,
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
