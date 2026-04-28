import json
import logging
import os
import asyncio
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from ...core.config import settings
from ...services.alarm.sanitizer import clean_exaone_tokens
from ...services.llm_service import LLMService
from ...services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)
_WEATHER_MESSAGE_MAX_CHARS = 3500
_MORNING_MIN_TEXT_LEN = 20
KST = ZoneInfo("Asia/Seoul")
DEFAULT_PERSONA_NAME = "애니 (Annie)"
PERSONA_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../data/persona_config.json")
_WEEKDAY_PERSONA_KEYS = (
    ("0", "mon", "monday", "월", "월요일"),
    ("1", "tue", "tuesday", "화", "화요일"),
    ("2", "wed", "wednesday", "수", "수요일"),
    ("3", "thu", "thursday", "목", "목요일"),
    ("4", "fri", "friday", "금", "금요일"),
    ("5", "sat", "saturday", "토", "토요일"),
    ("6", "sun", "sunday", "일", "일요일"),
)


def _resolve_persona_setting(personas: Any, persona_name: str) -> Optional[str]:
    if not isinstance(personas, dict):
        return None

    persona_data = personas.get(persona_name)
    if isinstance(persona_data, dict):
        return str(persona_data.get("setting", "") or "")

    normalized_target = re.sub(r"\s+", "", persona_name)
    for key, candidate in personas.items():
        if not isinstance(candidate, dict):
            continue
        normalized_key = re.sub(r"\s+", "", str(key))
        if not normalized_key:
            continue
        if normalized_key == normalized_target:
            return str(candidate.get("setting", "") or "")
        if normalized_target.endswith(normalized_key) or normalized_key.endswith(normalized_target):
            return str(candidate.get("setting", "") or "")

    return None


def load_persona_profile(
    *,
    now: Optional[datetime] = None,
    config_path: Optional[str] = None,
) -> Tuple[str, str]:
    active_persona = DEFAULT_PERSONA_NAME
    selected_persona = DEFAULT_PERSONA_NAME
    path = config_path or PERSONA_CONFIG_PATH

    try:
        if not os.path.exists(path):
            return DEFAULT_PERSONA_NAME, ""

        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)

        active_persona = str(config.get("active_persona") or DEFAULT_PERSONA_NAME).strip() or DEFAULT_PERSONA_NAME
        selected_persona = active_persona

        weekday_personas = config.get("weekday_personas")
        if isinstance(weekday_personas, dict):
            now_kst = (now or datetime.now(KST)).astimezone(KST)
            for key in _WEEKDAY_PERSONA_KEYS[now_kst.weekday()]:
                candidate = weekday_personas.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    selected_persona = candidate.strip()
                    break

        setting = _resolve_persona_setting(config.get("personas"), selected_persona)
        if setting is None and selected_persona != active_persona:
            setting = _resolve_persona_setting(config.get("personas"), active_persona)
        return selected_persona, setting or ""
    except Exception as e:
        logger.error("Failed to load persona config: %s", e)
        return DEFAULT_PERSONA_NAME, ""


def _select_culture_context(
    lec_results: Optional[str],
    steam_summary: Optional[str],
    inven_digest: Optional[str],
) -> str:
    lec_text = (lec_results or "").strip()
    if lec_text:
        return lec_text

    fragments = [text.strip() for text in (steam_summary, inven_digest) if (text or "").strip()]
    if fragments:
        return "\n".join(fragments)

    return "없음"


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
        f"날씨 확인하고 오늘도 좋은 하루 보내."
    )


def _normalize_weather_status(status: str) -> str:
    return re.sub(r"\s*[☀-🫧]+$", "", (status or "")).strip()


def _build_weather_snapshot_prefix(
    *,
    temp: str,
    weather_status: str,
    pop: str,
    max_temp: str = "N/A",
) -> str:
    segments = [f"서울 기준 지금 {temp}°C", f"하늘 상태는 {_normalize_weather_status(weather_status) or weather_status}"]
    if max_temp and max_temp != "N/A":
        segments.append(f"낮 최고 {max_temp}°C")
    if pop and pop != "N/A":
        segments.append(f"강수확률 {pop}%")
    return "<b>[오늘 날씨 한 줄 요약]</b> " + ", ".join(segments) + "."


def _ensure_weather_snapshot_prefix(
    *,
    text: str,
    temp: str,
    weather_status: str,
    pop: str,
    max_temp: str = "N/A",
) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return normalized

    prefix = _build_weather_snapshot_prefix(
        temp=temp,
        weather_status=weather_status,
        pop=pop,
        max_temp=max_temp,
    )
    if normalized.startswith(prefix):
        return normalized

    # 초반 2~3문장 안에 "기온 숫자까지 포함된 날씨 정보"가 없으면
    # 앞에 고정 스냅샷을 붙여 텔레그램에서 무심코 넘기지 않도록 한다.
    lead_text = normalized.split("\n\n", 1)[0].strip()
    if not lead_text:
        lead_text = normalized[:220]
    else:
        lead_text = lead_text[:220]

    status_core = _normalize_weather_status(weather_status)
    temp_patterns = []
    if temp:
        temp_patterns.extend(
            [
                rf"{re.escape(str(temp))}\s*°C",
                rf"{re.escape(str(temp))}\s*도",
                rf"기온[^0-9]{{0,10}}{re.escape(str(temp))}",
                rf"현재[^0-9]{{0,10}}{re.escape(str(temp))}",
            ]
        )
    has_temp_near_front = any(re.search(pattern, lead_text) for pattern in temp_patterns)
    has_weather_context_near_front = any(
        marker in lead_text
        for marker in (
            "날씨",
            "기온",
            "강수",
            "하늘",
            status_core or "",
        )
        if marker
    )

    if has_temp_near_front and has_weather_context_near_front:
        return normalized

    return f"{prefix}\n\n{normalized}"


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


def _format_weekly_derivatives_briefing(text: Optional[str]) -> str:
    """주간 파생 브리핑 문자열을 프롬프트에 넣기 좋은 평문으로 정리한다."""
    raw = (text or "").strip()
    if not raw:
        return "데이터 없음"

    if raw.startswith("주간 국내 파생심리 참고:"):
        return raw

    normalized = re.sub(r"</?b>", "", raw)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()

    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    cleaned_lines = []
    for line in lines:
        if re.fullmatch(r"\[[^\]]+\]", line):
            continue
        if line.startswith("-"):
            line = line[1:].strip()
        if line:
            cleaned_lines.append(line)

    if not cleaned_lines:
        return "데이터 없음"

    def _to_sentence(line: str) -> str:
        def _regime_phrase(regime: str) -> str:
            return f"{regime}였다." if "우위" in regime else f"{regime}이었다."

        if line.startswith("지난주") and ": 점수 " in line and "/" in line:
            label, rest = line.split(": 점수 ", 1)
            score, regime = [part.strip() for part in rest.split("/", 1)]
            return f"{label}는 점수 {score}로 {_regime_phrase(regime)}"
        if line.startswith("전주") and ": 점수 " in line and "/" in line:
            label, rest = line.split(": 점수 ", 1)
            score, regime = [part.strip() for part in rest.split("/", 1)]
            return f"{label}는 점수 {score}로 {_regime_phrase(regime)}"
        if line.startswith("점수 변화:"):
            return f"점수 변화는 {line.split(':', 1)[1].strip()}였다."
        if line.startswith("Put/Call(매수잔량) 평균:"):
            body = line.split(":", 1)[1].strip()
            if "(" in body and body.endswith(")"):
                value, tail = body.split("(", 1)
                return f"Put/Call(매수잔량) 평균은 {value.strip()}였고 {tail[:-1].strip()}."
            return f"Put/Call(매수잔량) 평균은 {body}였다."
        if line.startswith("풋-콜 OI증감 격차:"):
            body = line.split(":", 1)[1].strip()
            if "(" in body and body.endswith(")"):
                value, tail = body.split("(", 1)
                return f"풋-콜 OI증감 격차는 {value.strip()}였고 {tail[:-1].strip()}."
            return f"풋-콜 OI증감 격차는 {body}였다."
        if line.startswith("관측 구간:"):
            return f"관측 구간은 {line.split(':', 1)[1].strip()}였다."
        if line.startswith("코스피 수익률:"):
            return f"코스피 수익률은 {line.split(':', 1)[1].strip()}였다."
        return line if line.endswith((".", "!", "?")) else f"{line}."

    sentences = [_to_sentence(line) for line in cleaned_lines]
    return f"주간 국내 파생심리 참고: {' '.join(sentences)}"


async def fetch_briefing_context() -> Tuple[Optional[Any], Optional[Any], Optional[str], Optional[Dict], Optional[str], Optional[str]]:
    """모닝 브리핑용 부가 데이터(경제/시장전망/미세먼지/문화/선물옵션/주간파생)를 병렬 수집한다."""
    economic_snapshot = None
    dust_alarm = None
    culture_context = None
    futures_options_data = None
    market_outlook_news = None
    weekly_derivatives_briefing = None

    try:
        from ..economy.economy_service import EconomyService
        from ..economy.kr_derivatives_weekly_briefing import (
            build_weekly_derivatives_briefing,
            get_latest_option_snapshot_summary,
        )
        from ...integrations.air_korea.air_korea_client import air_korea_client
        from .esports_results import fetch_lec_results_summary
        from .steam import load_monthly_steam_ranking_summary
        from .rss import load_recent_inven_game_digest

        logger.info("Fetching economic, market outlook, dust, culture, and derivatives data for morning briefing...")

        econ_task = EconomyService.get_morning_snapshot()  # 캐싱 로직은 EconomyService 내부 참고
        market_news_task = asyncio.to_thread(EconomyService.load_market_outlook_news_context)
        dust_task = air_korea_client.get_latest_active_alarm(district_name="서울")
        lec_task = fetch_lec_results_summary(limit=10, lookback_hours=48, max_chars=0)
        steam_task = asyncio.to_thread(load_monthly_steam_ranking_summary)
        inven_task = asyncio.to_thread(load_recent_inven_game_digest)
        options_task = asyncio.to_thread(get_latest_option_snapshot_summary)
        now_kst = datetime.now(KST)
        if now_kst.weekday() == 0:
            weekly_derivatives_task = build_weekly_derivatives_briefing(now=now_kst)
        else:
            weekly_derivatives_task = asyncio.sleep(0, result=None)

        (
            econ_result,
            market_news_result,
            dust_result,
            lec_result,
            steam_result,
            inven_result,
            options_result,
            weekly_derivatives_result,
        ) = await asyncio.gather(
            econ_task,
            market_news_task,
            dust_task,
            lec_task,
            steam_task,
            inven_task,
            options_task,
            weekly_derivatives_task,
            return_exceptions=True,
        )

        if not isinstance(econ_result, Exception):
            economic_snapshot = econ_result
        if not isinstance(market_news_result, Exception):
            market_outlook_news = market_news_result
        if not isinstance(dust_result, Exception):
            dust_alarm = dust_result
        culture_context = _select_culture_context(
            None if isinstance(lec_result, Exception) else lec_result,
            None if isinstance(steam_result, Exception) else steam_result,
            None if isinstance(inven_result, Exception) else inven_result,
        )
        if not isinstance(options_result, Exception):
            futures_options_data = options_result
        if not isinstance(weekly_derivatives_result, Exception):
            weekly_derivatives_briefing = _format_weekly_derivatives_briefing(weekly_derivatives_result)
            
    except Exception as e:
        logger.error("Failed to fetch additional data for morning briefing: %s", e)

    return (
        economic_snapshot,
        dust_alarm,
        culture_context,
        futures_options_data,
        market_outlook_news,
        weekly_derivatives_briefing,
    )


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
    culture_context: Optional[str] = None,
    futures_options_data: Optional[Dict] = None,
    market_outlook_news: Optional[str] = None,
    weekly_derivatives_briefing: Optional[str] = None,
) -> str:
    """날씨 정보를 LLM으로 자연어 메시지로 변환한다."""
    def _trim_for_telegram(text: str, max_chars: int = _WEATHER_MESSAGE_MAX_CHARS) -> str:
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        cut_idx = max(
            truncated.rfind("\n"),
            truncated.rfind(". "),
            truncated.rfind("! "),
            truncated.rfind("? "),
        )
        if cut_idx >= 200:
            truncated = truncated[:cut_idx]
        return truncated.rstrip() + "\n\n... (이하 생략)"

    def _is_valid_message(text: str) -> bool:
        return len((text or "").strip()) >= _MORNING_MIN_TEXT_LEN

    def _finalize_message(raw_text: str) -> str:
        normalized = clean_exaone_tokens(raw_text).strip()
        if not _is_valid_message(normalized):
            return ""
        normalized = _ensure_weather_snapshot_prefix(
            text=normalized,
            temp=temp,
            weather_status=weather_status,
            pop=pop,
            max_temp=max_temp,
        )
        return _trim_for_telegram(normalized)

    def _format_futures_options_data(data: Optional[Dict]) -> str:
        if not data:
            return "데이터 없음"

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

        try:
            # 1) 주간 파생용 스냅샷 캐시 포맷(권장 경로)
            if "call_bid_total" in data and "put_bid_total" in data:
                total_call_ask = _to_int(data.get("call_ask_total"))
                total_call_bid = _to_int(data.get("call_bid_total"))
                total_put_ask = _to_int(data.get("put_ask_total"))
                total_put_bid = _to_int(data.get("put_bid_total"))
                total_call_oi_change = _to_int(data.get("call_oi_change_total"))
                total_put_oi_change = _to_int(data.get("put_oi_change_total"))
                pcr = _to_float(data.get("put_call_bid_ratio"))
                trading_date = str(data.get("trading_date") or "")
                if len(trading_date) == 8:
                    trading_date = f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:8]}"

                return (
                    f"{trading_date} 장마감 스냅샷 | "
                    f"콜옵션 매도잔량:{total_call_ask:,}, 매수잔량:{total_call_bid:,}, OI증감:{total_call_oi_change:+,} | "
                    f"풋옵션 매도잔량:{total_put_ask:,}, 매수잔량:{total_put_bid:,}, OI증감:{total_put_oi_change:+,} | "
                    f"Put/Call(매수잔량):{pcr:.2f}"
                )

            # 2) (하위호환) 실시간 옵션 전광판 raw payload 포맷
            calls = data.get("output1", [])
            puts = data.get("output2", [])
            total_call_ask = sum(_to_int(c.get("total_askp_rsqn")) for c in calls if isinstance(c, dict))
            total_call_bid = sum(_to_int(c.get("total_bidp_rsqn")) for c in calls if isinstance(c, dict))
            total_put_ask = sum(_to_int(p.get("total_askp_rsqn")) for p in puts if isinstance(p, dict))
            total_put_bid = sum(_to_int(p.get("total_bidp_rsqn")) for p in puts if isinstance(p, dict))
            total_call_oi_change = sum(_to_int(c.get("otst_stpl_qty_icdc")) for c in calls if isinstance(c, dict))
            total_put_oi_change = sum(_to_int(p.get("otst_stpl_qty_icdc")) for p in puts if isinstance(p, dict))

            return (
                f"콜옵션 매도잔량:{total_call_ask:,}, 매수잔량:{total_call_bid:,}, OI증감:{total_call_oi_change:+,} | "
                f"풋옵션 매도잔량:{total_put_ask:,}, 매수잔량:{total_put_bid:,}, OI증감:{total_put_oi_change:+,}"
            )
        except Exception as e:
            logger.error("Failed to format futures/options data for LLM: %s", e)
            return "데이터 없음"

    llm = LLMService.get_instance()
    has_primary_paid = llm.settings.is_paid_configured()
    has_openrouter_fallback = bool(
        settings.open_api_key
        and settings.morning_openrouter_model
        and settings.morning_openrouter_base_url
    )
    has_remote_fallback = llm.settings.is_remote_configured()

    if not (has_primary_paid or has_openrouter_fallback or has_remote_fallback):
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

            econ_str = EconomyService.format_snapshot_for_llm(
                economic_snapshot,
                include_intraday_kr_indices=False,
            )
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

    fo_str = _format_futures_options_data(futures_options_data)
    weekly_fo_str = _format_weekly_derivatives_briefing(weekly_derivatives_briefing)

    # 페르소나 설정 로드
    persona_name, persona_setting = load_persona_profile()

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
        market_outlook_news=(market_outlook_news or "데이터 없음"),
        dust_info=dust_str,
        culture_context=(culture_context or "없음"),
        futures_options_data=fo_str,
        weekly_derivatives_briefing=weekly_fo_str,
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
        stop_tokens = ["Ok,", "사용자가", "지시사항"]
        creative_text = ""

        # 1) AI_REPORT 우선
        if has_primary_paid:
            try:
                logger.info("모닝브리핑: AI_REPORT 우선 (model=%s)", llm.settings.ai_report_model)
                creative_text = llm.generate_paid_chat(
                    messages,
                    max_tokens=4096,
                    temperature=0.85,
                    model=llm.settings.ai_report_model,
                    stop=stop_tokens,
                    api_key=llm.settings.ai_report_api_key,
                    base_url=llm.settings.ai_report_base_url,
                )
            except Exception as e:
                logger.warning("모닝브리핑: AI_REPORT 예외, 다음 폴백 진행: %s", e)
                creative_text = ""

            finalized = _finalize_message(creative_text)
            if finalized:
                logger.info("모닝브리핑: AI_REPORT 응답 성공 (len=%d)", len(finalized))
                return finalized
            logger.warning("모닝브리핑: AI_REPORT 응답 실패/짧음, 다음 폴백 진행")

        # 2) OpenRouter fallback
        if has_openrouter_fallback:
            try:
                logger.info(
                    "모닝브리핑: OpenRouter 폴백 (model=%s)",
                    settings.morning_openrouter_model,
                )
                creative_text = llm.generate_paid_chat(
                    messages,
                    max_tokens=4096,
                    temperature=0.85,
                    model=settings.morning_openrouter_model,
                    stop=stop_tokens,
                    api_key=settings.open_api_key,
                    base_url=settings.morning_openrouter_base_url,
                )
            except Exception as e:
                logger.warning("모닝브리핑: OpenRouter 예외, remote-only 폴백 진행: %s", e)
                creative_text = ""

            finalized = _finalize_message(creative_text)
            if finalized:
                logger.info("모닝브리핑: OpenRouter 응답 성공 (len=%d)", len(finalized))
                return finalized
            logger.warning("모닝브리핑: OpenRouter 응답 실패/짧음, remote-only 폴백 진행")

        # 3) remote only (유료 폴백 금지)
        if has_remote_fallback:
            logger.info("모닝브리핑: remote 폴백(유료 금지)")
            creative_text = llm.generate_chat(
                messages,
                max_tokens=4096,
                temperature=0.85,
                stop=stop_tokens,
                allow_paid_fallback=False,
            )
            finalized = _finalize_message(creative_text)
            if finalized:
                return finalized

        # 4) 옵션: remote 실패 후 마지막 유료 폴백 허용
        if settings.morning_allow_paid_fallback and has_remote_fallback:
            logger.info("모닝브리핑: 최후 유료 폴백 허용")
            creative_text = llm.generate_chat(
                messages,
                max_tokens=4096,
                temperature=0.85,
                stop=stop_tokens,
                allow_paid_fallback=True,
            )
            finalized = _finalize_message(creative_text)
            if finalized:
                return finalized

        logger.warning("LLM 날씨 메시지 생성 실패/짧음, fallback 사용. last_error=%s", llm.get_last_error())
        return get_fallback_message(
            temp=temp,
            weather_status=weather_status,
            pop=pop,
            base_date=base_date,
            base_time=base_time,
            max_temp=max_temp,
        )
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
