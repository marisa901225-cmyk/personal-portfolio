import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

# 기상청 단기/초단기예보 조회 서비스 (공공데이터포털)
KMA_API_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
KMA_ULTRA_API_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst"

# 서울 중구 격자 좌표 (기상청 Lambert Conformal Conic Projection)
SEOUL_NX = 60
SEOUL_NY = 127


def get_base_times_ordered() -> List[Dict[str, str]]:
    """단기예보 base 시각 후보를 최신순으로 반환한다."""
    KST = ZoneInfo("Asia/Seoul")
    now = datetime.now(KST)
    ordered_times: List[Dict[str, str]] = []

    # 가능한 모든 발표 시간대 (오늘+어제)
    all_slots = [
        (0, "2300"),
        (0, "2000"),
        (0, "1700"),
        (0, "1400"),
        (0, "1100"),
        (0, "0800"),
        (0, "0500"),
        (0, "0200"),
        (1, "2300"),
        (1, "2000"),
        (1, "1700"),
        (1, "1400"),
    ]

    for days_back, b_time in all_slots:
        b_date_dt = now - timedelta(days=days_back)
        b_date = b_date_dt.strftime("%Y%m%d")

        pub_hour = int(b_time[:2])
        pub_time = b_date_dt.replace(hour=pub_hour, minute=10, second=0, microsecond=0)
        if now >= pub_time:
            ordered_times.append({"base_date": b_date, "base_time": b_time})

    return ordered_times


def get_base_time() -> tuple[str, str]:
    """최신 단기예보 base_date/base_time 한 쌍을 반환한다."""
    times = get_base_times_ordered()
    KST = ZoneInfo("Asia/Seoul")
    if times:
        return times[0]["base_date"], times[0]["base_time"]
    return datetime.now(KST).strftime("%Y%m%d"), "0200"


def get_ultra_base_times_ordered(max_slots: int = 8) -> List[Dict[str, str]]:
    """초단기예보 base 시각 후보(30분 단위)를 최신순으로 반환한다."""
    KST = ZoneInfo("Asia/Seoul")
    now = datetime.now(KST)
    floored_minute = (now.minute // 30) * 30
    anchor = now.replace(minute=floored_minute, second=0, microsecond=0)

    ordered_times: List[Dict[str, str]] = []
    for idx in range(max_slots):
        slot = anchor - timedelta(minutes=30 * idx)
        ordered_times.append(
            {
                "base_date": slot.strftime("%Y%m%d"),
                "base_time": slot.strftime("%H%M"),
            }
        )
    return ordered_times


def get_sky_status(sky_value: str) -> str:
    """SKY 코드를 사람이 읽을 텍스트로 변환한다."""
    mapping = {
        "1": "맑음 ☀️",
        "3": "구름많음 ☁️",
        "4": "흐림 ☁️",
    }
    return mapping.get(sky_value, f"알 수 없음({sky_value})")


def get_pty_status(pty_value: str) -> str:
    """PTY 코드를 사람이 읽을 텍스트로 변환한다."""
    mapping = {
        "0": "없음",
        "1": "비 🌧️",
        "2": "비/눈 🌨️",
        "3": "눈 ❄️",
        "4": "소나기 🌦️",
    }
    return mapping.get(pty_value, "없음")


def _select_earliest_values(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """카테고리별로 가장 가까운 예측시각 값을 선택한다."""
    selected: Dict[str, Dict[str, str]] = {}
    for item in items:
        category = str(item.get("category", ""))
        if not category:
            continue

        fcst_date = str(item.get("fcstDate", ""))
        fcst_time = str(item.get("fcstTime", ""))
        fcst_value = str(item.get("fcstValue", ""))
        sort_key = f"{fcst_date}{fcst_time}"

        prev = selected.get(category)
        if prev is None or sort_key < prev["sort_key"]:
            selected[category] = {
                "value": fcst_value,
                "date": fcst_date,
                "time": fcst_time,
                "sort_key": sort_key,
            }
    return selected


async def fetch_short_term_weather(
    service_key: str | Sequence[str],
    *,
    nx: int = SEOUL_NX,
    ny: int = SEOUL_NY,
    max_slots: int = 4,
) -> Optional[Dict[str, str]]:
    """단기예보 API를 조회해 핵심 날씨 데이터를 반환한다."""
    candidate_times = get_base_times_ordered()
    if not candidate_times:
        return None

    if isinstance(service_key, str):
        service_keys = [service_key]
    else:
        service_keys = [key for key in service_key if key]
    if not service_keys:
        return None

    async with httpx.AsyncClient() as client:
        for idx, key in enumerate(service_keys, 1):
            for slot in candidate_times[:max_slots]:
                params = {
                    "ServiceKey": key,
                    "base_date": slot["base_date"],
                    "base_time": slot["base_time"],
                    "nx": nx,
                    "ny": ny,
                    "numOfRows": 1000,
                    "pageNo": 1,
                    "dataType": "JSON",
                }

                try:
                    response = await client.get(KMA_API_URL, params=params, timeout=15.0)
                    logger.info("KMA short-term status[%s]: %s", idx, response.status_code)
                    if response.status_code != 200:
                        logger.error("KMA short-term body[%s]: %s", idx, response.text[:500])
                        continue

                    data = response.json()
                    result_code = data.get("response", {}).get("header", {}).get("resultCode")
                    if result_code == "03":
                        logger.warning(
                            "No short-term data yet for key[%s] %s %s. Trying older slot...",
                            idx,
                            slot["base_date"],
                            slot["base_time"],
                        )
                        continue
                    if result_code != "00":
                        error_msg = data.get("response", {}).get("header", {}).get("resultMsg", "Unknown error")
                        logger.error("KMA short-term error[%s] (%s): %s", idx, result_code, error_msg)
                        continue

                    items: List[Dict[str, Any]] = (
                        data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                    )
                    if not items:
                        logger.warning("No short-term forecast items returned for key[%s]", idx)
                        continue

                    by_category = _select_earliest_values(items)
                    temp = by_category.get("TMP", {}).get("value", "N/A")
                    max_temp = by_category.get("TMX", {}).get("value", "N/A")
                    sky = by_category.get("SKY", {}).get("value", "1")
                    pty = by_category.get("PTY", {}).get("value", "0")
                    pop = by_category.get("POP", {}).get("value", "0")

                    weather_status = get_pty_status(pty) if pty != "0" else get_sky_status(sky)
                    return {
                        "temp": temp,
                        "max_temp": max_temp,
                        "weather_status": weather_status,
                        "pop": pop,
                        "base_date": slot["base_date"],
                        "base_time": slot["base_time"],
                    }
                except Exception as e:
                    logger.error("Error fetching short-term weather[%s]: %s", idx, e)
                    continue

    logger.error("Failed to fetch short-term weather data after retries")
    return None


async def fetch_ultra_short_snapshot(
    service_key: str,
    *,
    nx: int = SEOUL_NX,
    ny: int = SEOUL_NY,
    max_slots: int = 8,
) -> Dict[str, str]:
    """초단기예보 API를 조회해 출근 직전 보강 데이터를 반환한다."""
    candidate_times = get_ultra_base_times_ordered(max_slots=max_slots)
    data: Optional[Dict[str, Any]] = None

    async with httpx.AsyncClient() as client:
        for slot in candidate_times:
            params = {
                "ServiceKey": service_key,
                "pageNo": 1,
                "numOfRows": 1000,
                "dataType": "JSON",
                "base_date": slot["base_date"],
                "base_time": slot["base_time"],
                "nx": nx,
                "ny": ny,
            }
            try:
                response = await client.get(KMA_ULTRA_API_URL, params=params, timeout=15.0)
                if response.status_code != 200:
                    continue

                body = response.json()
                result_code = body.get("response", {}).get("header", {}).get("resultCode")
                if result_code != "00":
                    continue

                items = body.get("response", {}).get("body", {}).get("items", {}).get("item", [])
                if items:
                    data = body
                    break
            except Exception as e:
                logger.debug("Ultra short fetch failed for %s: %s", slot, e)
                continue

    if not data:
        return {}

    items: List[Dict[str, Any]] = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
    if not items:
        return {}

    selected_all = _select_earliest_values(items)
    selected = {k: v for k, v in selected_all.items() if k in {"T1H", "PTY", "RN1", "REH", "WSD", "SKY"}}

    pty_value = selected.get("PTY", {}).get("value", "0")
    sky_value = selected.get("SKY", {}).get("value", "1")
    weather_status = get_pty_status(pty_value) if pty_value != "0" else get_sky_status(sky_value)

    base_cat = "T1H" if "T1H" in selected else ("PTY" if "PTY" in selected else "SKY")
    base_entry = selected.get(base_cat, {})

    return {
        "temp": selected.get("T1H", {}).get("value", ""),
        "rn1": selected.get("RN1", {}).get("value", ""),
        "reh": selected.get("REH", {}).get("value", ""),
        "wsd": selected.get("WSD", {}).get("value", ""),
        "weather_status": weather_status,
        "fcst_date": base_entry.get("date", ""),
        "fcst_time": base_entry.get("time", ""),
    }
