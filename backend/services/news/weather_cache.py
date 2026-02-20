"""
날씨 데이터 캐시 모듈

05시 프리페치 수집 데이터를 저장하고 07시 발송 시 사용하기 위한 캐시 관리 모듈.
파일 기반 JSON 캐시를 사용.
"""
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# 캐시 디렉토리 경로
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "weather_cache"
KST = ZoneInfo("Asia/Seoul")


@dataclass
class WeatherData:
    """날씨 데이터 구조"""
    message: str  # LLM으로 생성된 최종 메시지
    temp: str  # 기온 (°C)
    weather_status: str  # 날씨 상태 (예: "맑음 ☀️")
    pop: str  # 강수확률 (%)
    base_date: str  # 발표일자 (YYYYMMDD)
    base_time: str  # 발표시각 (HHMM)
    cached_at: str  # 캐시 저장 시각 (ISO format)
    max_temp: str = "N/A"  # 오늘 최고기온 (TMX)
    
    @classmethod
    def from_dict(cls, data: dict) -> "WeatherData":
        """dict에서 WeatherData 객체 생성"""
        payload = dict(data)
        payload.setdefault("max_temp", "N/A")
        return cls(**payload)
    
    def to_dict(self) -> dict:
        """WeatherData 객체를 dict로 변환"""
        return asdict(self)


def _ensure_cache_dir() -> None:
    """캐시 디렉토리가 없으면 생성"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_cache_filename(base_date: str, base_time: str) -> str:
    """캐시 파일명 생성: {date}_{time}.json"""
    return f"{base_date}_{base_time}.json"


def _get_cache_path(base_date: str, base_time: str) -> Path:
    """캐시 파일 전체 경로 반환"""
    return CACHE_DIR / _get_cache_filename(base_date, base_time)


def _get_last_success_path() -> Path:
    """마지막 성공 캐시 파일 경로"""
    return CACHE_DIR / "last_success.json"


def save_weather_cache(data: WeatherData) -> None:
    """날씨 데이터를 캐시에 저장
    
    Args:
        data: 저장할 날씨 데이터
    """
    try:
        _ensure_cache_dir()
        cache_path = _get_cache_path(data.base_date, data.base_time)
        
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.info(f"Weather cache saved: {cache_path.name}")
        
        # 성공 시 last_success 캐시도 업데이트
        save_last_success_cache(data)
        
    except Exception as e:
        logger.error(f"Failed to save weather cache: {e}", exc_info=True)


def load_weather_cache() -> Optional[WeatherData]:
    """오늘 날짜의 가장 최신 캐시 로드
    
    Returns:
        캐시된 날씨 데이터 중 가장 최신 것 또는 None
    """
    try:
        _ensure_cache_dir()
        now = datetime.now(KST)
        today = now.strftime("%Y%m%d")
        
        # 오늘 날짜의 모든 캐시 파일 찾기 (YYYYMMDD_*.json)
        cache_files = list(CACHE_DIR.glob(f"{today}_*.json"))
        
        if not cache_files:
            logger.debug(f"No weather cache found for today: {today}")
            return None
        
        # 가장 최신 base_time 파일 선택 (파일명 정렬 활용)
        cache_files.sort(reverse=True)
        latest_cache_path = cache_files[0]
        
        with open(latest_cache_path, "r", encoding="utf-8") as f:
            data_dict = json.load(f)
        
        data = WeatherData.from_dict(data_dict)
        logger.info(f"Weather cache loaded: {latest_cache_path.name}")
        return data
        
    except Exception as e:
        logger.error(f"Failed to load weather cache: {e}", exc_info=True)
        return None


def is_cache_fresh() -> bool:
    """오늘 날짜의 유효한 캐시가 있는지 확인
    
    Returns:
        True if any cache exists for today
    """
    # load_weather_cache가 이미 오늘 날짜 파일만 검색하므로
    # 단순히 로드가 성공하는지만 확인하면 됨
    return load_weather_cache() is not None


def save_last_success_cache(data: WeatherData) -> None:
    """마지막 성공 캐시 저장 (폴백용)
    
    Args:
        data: 저장할 날씨 데이터
    """
    try:
        _ensure_cache_dir()
        last_success_path = _get_last_success_path()
        
        with open(last_success_path, "w", encoding="utf-8") as f:
            json.dump(data.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.debug(f"Last success cache updated")
        
    except Exception as e:
        logger.error(f"Failed to save last success cache: {e}", exc_info=True)


def load_last_success_cache() -> Optional[WeatherData]:
    """마지막 성공 캐시 로드 (폴백용)
    
    Returns:
        마지막 성공 날씨 데이터 또는 None
    """
    try:
        last_success_path = _get_last_success_path()
        
        if not last_success_path.exists():
            logger.warning("Last success cache not found")
            return None
        
        with open(last_success_path, "r", encoding="utf-8") as f:
            data_dict = json.load(f)
        
        data = WeatherData.from_dict(data_dict)
        logger.info("Last success cache loaded (fallback)")
        return data
        
    except Exception as e:
        logger.error(f"Failed to load last success cache: {e}", exc_info=True)
        return None


def clear_old_caches() -> None:
    """오래된 캐시 파일 삭제 (7일 이상 지난 것)
    
    last_success.json은 유지
    """
    try:
        _ensure_cache_dir()
        now = datetime.now(KST)
        
        for cache_file in CACHE_DIR.glob("*.json"):
            # last_success.json은 건너뛰기
            if cache_file.name == "last_success.json":
                continue
            
            # 파일명에서 날짜 추출 (YYYYMMDD_HHMM.json)
            try:
                date_str = cache_file.stem.split("_")[0]
                cache_date = datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=KST)
                
                # 7일 이상 지난 파일 삭제
                if (now - cache_date).days > 7:
                    cache_file.unlink()
                    logger.debug(f"Deleted old cache: {cache_file.name}")
            except (ValueError, IndexError):
                # 파일명 형식이 맞지 않으면 건너뛰기
                continue
                
    except Exception as e:
        logger.error(f"Failed to clear old caches: {e}", exc_info=True)
