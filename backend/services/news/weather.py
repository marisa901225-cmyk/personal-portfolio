import logging
import httpx
import json
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from ...core.config import settings
from ...integrations.telegram import send_telegram_message
from ...services.llm_service import LLMService
from ...services.alarm.sanitizer import clean_exaone_tokens
from ...services.prompt_loader import load_prompt

logger = logging.getLogger(__name__)

# 기상청 단기예보 조회 서비스 (공공데이터포털)
KMA_API_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"

# 서울 중구 격자 좌표 (기상청 Lambert Conformal Conic Projection)
SEOUL_NX = 60
SEOUL_NY = 127

def _get_fallback_message(temp: str, weather_status: str, pop: str, base_date: str, base_time: str) -> str:
    """JSON 파일에서 폴백 템플릿을 읽어와서 메시지를 생성한다."""
    fallback_path = os.path.join(os.path.dirname(__file__), "../../data/weather_fallback.json")
    try:
        if os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8") as f:
                template = json.load(f).get("weather_fallback", "")
                if template:
                    return template.format(
                        temp=temp,
                        weather_status=weather_status,
                        pop=pop,
                        base_date=base_date,
                        base_time=base_time
                    )
    except Exception as e:
        logger.error(f"Failed to load weather fallback JSON: {e}")
        
    # JSON 로드 실패 시의 최후의 보루 (하드코딩)
    return (
        f"<b>[오늘의 날씨 정보 - 서울]</b> 🌦️\n\n"
        f"🌡️ <b>기온</b>: {temp}°C\n"
        f"☁️ <b>날씨</b>: {weather_status}\n"
        f"☔ <b>강수확률</b>: {pop}%\n\n"
        f"📅 <b>발표시각</b>: {base_date} {base_time}\n\n"
        f"날씨 확인하고 따뜻하게 입고 나가, LO! ❤️"
    )

def get_base_times_ordered() -> List[Dict[str, str]]:
    """현재 시각 기준으로 시도해볼 수 있는 발표시각들을 최신순으로 반환
    
    발표시각: 02:10, 05:10, 08:10, 11:10, 14:10, 17:10, 20:10, 23:10
    Base_time: 0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300
    """
    now = datetime.now()
    ordered_times = []
    
    # 가능한 모든 발표 시간대 (오늘+어제)
    all_slots = [
        (0, "2300"), (0, "2000"), (0, "1700"), (0, "1400"), 
        (0, "1100"), (0, "0800"), (0, "0500"), (0, "0200"),
        (1, "2300"), (1, "2000"), (1, "1700"), (1, "1400")
    ]
    
    for days_back, b_time in all_slots:
        b_date_dt = now - timedelta(days=days_back)
        b_date = b_date_dt.strftime("%Y%m%d")
        
        # 발표 시각은 base_time + 10분
        pub_hour = int(b_time[:2])
        pub_time = b_date_dt.replace(hour=pub_hour, minute=10, second=0, microsecond=0)
        
        # 현재 시각보다 이전인 발표 시간대만 추가
        if now >= pub_time:
            ordered_times.append({"base_date": b_date, "base_time": b_time})
            
    return ordered_times

def get_base_time() -> tuple[str, str]:
    """구성된 리스트의 첫 번째 항목(가장 최신)을 반환 (하위 호환성 유지)"""
    times = get_base_times_ordered()
    if times:
        return times[0]["base_date"], times[0]["base_time"]
    # 폴백
    return datetime.now().strftime("%Y%m%d"), "0200"

def get_sky_status(sky_value: str) -> str:
    """하늘상태 코드를 텍스트와 이모지로 변환
    
    SKY 코드: 1(맑음), 3(구름많음), 4(흐림)
    """
    mapping = {
        "1": "맑음 ☀️",
        "3": "구름많음 ☁️",
        "4": "흐림 ☁️",
    }
    return mapping.get(sky_value, f"알 수 없음({sky_value})")

def get_pty_status(pty_value: str) -> str:
    """강수형태 코드를 텍스트와 이모지로 변환
    
    PTY 코드: 0(없음), 1(비), 2(비/눈), 3(눈), 4(소나기)
    """
    mapping = {
        "0": "없음",
        "1": "비 🌧️",
        "2": "비/눈 🌨️",
        "3": "눈 ❄️",
        "4": "소나기 🌦️",
    }
    return mapping.get(pty_value, "없음")

async def generate_weather_message_with_llm(
    temp: str,
    weather_status: str,
    pop: str,
    base_date: str,
    base_time: str
) -> str:
    """LLM을 사용하여 날씨 정보를 자연스러운 메시지로 변환한다.
    
    Args:
        temp: 기온 (°C)
        weather_status: 날씨 상태 (예: "맑음 ☀️")
        pop: 강수확률 (%)
        base_date: 발표일자
        base_time: 발표시각
    
    Returns:
        LLM이 생성한 날씨 메시지 또는 폴백 메시지
    """
    llm = LLMService.get_instance()
    
    # LLM이 로드되지 않은 경우 폴백
    if not llm.is_loaded():
        return _get_fallback_message(temp, weather_status, pop, base_date, base_time)
    
    # LLM 프롬프트 구성 (외부 파일에서 로드)
    prompt_content = load_prompt(
        "weather_message",
        temp=temp,
        weather_status=weather_status,
        pop=pop,
        base_date=base_date,
        base_time=base_time
    )
    
    # 프롬프트 파일이 없는 경우 폴백
    if not prompt_content:
        logger.warning("Weather prompt file not found, using fallback")
        return _get_fallback_message(temp, weather_status, pop, base_date, base_time)
    
    messages = [
        {
            "role": "user",
            "content": prompt_content
        }
    ]
    
    try:
        creative_text = llm.generate_chat(
            messages,
            max_tokens=256,
            temperature=0.7,
            stop=["Ok,", "사용자가", "지시사항"]
        )
        creative_text = clean_exaone_tokens(creative_text)
        creative_text = creative_text.strip()
        
        # 생성 실패 시 폴백
        if not creative_text or len(creative_text) < 20:
            logger.warning("LLM generated empty or too short message, using fallback")
            return _get_fallback_message(temp, weather_status, pop, base_date, base_time)
        
        return creative_text
        
    except Exception as e:
        logger.error(f"LLM weather message generation failed: {e}", exc_info=True)
        # 에러 발생 시 폴백
        return _get_fallback_message(temp, weather_status, pop, base_date, base_time)

async def fetch_weather_forecast() -> Optional[str]:
    """기상청 단기예보 API를 호출하여 서울 지역 날씨 정보를 가져오고 포맷팅한다."""
    service_key = settings.kma_service_key
    if not service_key:
        logger.warning("KMA_SERVICE_KEY not set.")
        return None

    candidate_times = get_base_times_ordered()
    
    data = None
    target_date = ""
    target_time = ""
    
    async with httpx.AsyncClient() as client:
        # 최신 시간대부터 시도 (데이터가 없거나 에러나면 이전 시간대 시도)
        for time_slot in candidate_times[:4]:  # 최대 4개 시간대까지 시도 (충분히 과거로 폴백)
            target_date = time_slot["base_date"]
            target_time = time_slot["base_time"]
            
            params = {
                "serviceKey": service_key,
                "base_date": target_date,
                "base_time": target_time,
                "nx": SEOUL_NX,
                "ny": SEOUL_NY,
                "numOfRows": 100,
                "pageNo": 1,
                "dataType": "JSON"
            }

            try:
                response = await client.get(KMA_API_URL, params=params, timeout=15.0)
                
                # 디버깅: 요청 URL 및 응답 상태 확인 (이중 인코딩 체크용)
                logger.info(f"REQUEST URL: {response.request.url}")
                logger.info(f"STATUS: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"BODY: {response.text[:500]}")
                    continue
                
                resp_data = response.json()
                result_code = resp_data.get("response", {}).get("header", {}).get("resultCode")
                
                if result_code == "00":
                    data = resp_data
                    logger.info(f"Successfully fetched weather for {target_date} {target_time}")
                    break
                elif result_code == "03": # NO_DATA_ERROR
                    logger.warning(f"No weather data yet for {target_date} {target_time}. Trying previous slot...")
                    continue
                else:
                    error_msg = resp_data.get("response", {}).get("header", {}).get("resultMsg", "Unknown error")
                    logger.error(f"KMA API error ({result_code}): {error_msg}")
                    continue
                    
            except Exception as e:
                logger.error(f"Error fetching from KMA API: {e}")
                continue

    if not data:
        logger.error("Failed to fetch weather data after multiple attempts.")
        return None

    try:
        # 응답 구조: response > body > items > item (리스트)
        items: List[Dict[str, Any]] = data.get("response", {}).get("body", {}).get("items", {}).get("item", [])
        if not items:
            logger.warning("No forecast data items returned from KMA API")
            return None


        # 카테고리별 데이터 추출 (첫 번째 시간대 기준)
        forecast_data = {}
        for item in items:
            category = item.get("category")
            fcst_value = item.get("fcstValue")
            fcst_date = item.get("fcstDate")
            fcst_time = item.get("fcstTime")
            
            # 첫 번째 시간대 데이터만 사용 (가장 가까운 예보)
            if category not in forecast_data:
                forecast_data[category] = {
                    "value": fcst_value,
                    "date": fcst_date,
                    "time": fcst_time
                }

        # 필요한 카테고리: TMP(기온), SKY(하늘상태), PTY(강수형태), POP(강수확률)
        temp = forecast_data.get("TMP", {}).get("value", "N/A")
        sky = forecast_data.get("SKY", {}).get("value", "1")
        pty = forecast_data.get("PTY", {}).get("value", "0")
        pop = forecast_data.get("POP", {}).get("value", "0")

        sky_text = get_sky_status(sky)
        pty_text = get_pty_status(pty)

        # 강수형태가 있으면 그것을 우선 표시
        weather_status = pty_text if pty != "0" else sky_text

        # LLM을 사용하여 자연스러운 메시지 생성
        message = await generate_weather_message_with_llm(
            temp=temp,
            weather_status=weather_status,
            pop=pop,
            base_date=target_date,
            base_time=target_time
        )
        return message

    except Exception as e:
        logger.error(f"Failed to fetch weather from KMA API: {e}", exc_info=True)
        return None

async def send_weather_notification():
    """날씨 정보를 텔레그램으로 전송한다."""
    message = await fetch_weather_forecast()
    if message:
        await send_telegram_message(message)
        logger.info("Weather notification sent successfully.")
    else:
        logger.warning("Weather notification was empty, nothing sent.")

if __name__ == "__main__":
    import asyncio
    async def test():
        print("Testing KMA Short-term Forecast API...")
        msg = await fetch_weather_forecast()
        print("-" * 50)
        print(msg if msg else "Failed to get weather message.")
        print("-" * 50)
    
    asyncio.run(test())
