"""
날씨 캐시 모듈 테스트
"""
import pytest
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.services.news.weather_cache import (
    WeatherData,
    save_weather_cache,
    load_weather_cache,
    is_cache_fresh,
    save_last_success_cache,
    load_last_success_cache,
    clear_old_caches,
    CACHE_DIR,
)


@pytest.fixture
def clean_cache_dir():
    """테스트 전후 캐시 디렉토리 정리"""
    # 테스트 전 정리
    if CACHE_DIR.exists():
        for cache_file in CACHE_DIR.glob("*.json"):
            cache_file.unlink()
    
    yield
    
    # 테스트 후 정리
    if CACHE_DIR.exists():
        for cache_file in CACHE_DIR.glob("*.json"):
            cache_file.unlink()


@pytest.fixture
def sample_weather_data():
    """샘플 날씨 데이터"""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    today = now.strftime("%Y%m%d")
    
    return WeatherData(
        message="안녕, LO! 오늘 서울 날씨는 맑음이야. 기온은 15°C, 강수확률은 10%야. 따뜻하게 입고 나가!",
        temp="15",
        weather_status="맑음 ☀️",
        pop="10",
        base_date=today,
        base_time="0500",
        cached_at=now.isoformat()
    )


def test_save_and_load_cache(clean_cache_dir, sample_weather_data):
    """캐시 저장 및 로드 테스트"""
    # 저장
    save_weather_cache(sample_weather_data)
    
    # 로드
    loaded_data = load_weather_cache()
    
    assert loaded_data is not None
    assert loaded_data.message == sample_weather_data.message
    assert loaded_data.temp == sample_weather_data.temp
    assert loaded_data.weather_status == sample_weather_data.weather_status
    assert loaded_data.pop == sample_weather_data.pop
    assert loaded_data.base_date == sample_weather_data.base_date
    assert loaded_data.base_time == sample_weather_data.base_time


def test_is_cache_fresh(clean_cache_dir, sample_weather_data):
    """캐시 신선도 체크 테스트"""
    # 캐시 없음
    assert is_cache_fresh() == False
    
    # 캐시 저장
    save_weather_cache(sample_weather_data)
    
    # 오늘 05시 캐시 있음
    assert is_cache_fresh() == True


def test_last_success_fallback(clean_cache_dir, sample_weather_data):
    """last_success 캐시 저장/로드 테스트"""
    # 저장
    save_last_success_cache(sample_weather_data)
    
    # 로드
    loaded_data = load_last_success_cache()
    
    assert loaded_data is not None
    assert loaded_data.message == sample_weather_data.message
    assert loaded_data.base_date == sample_weather_data.base_date
    assert loaded_data.base_time == sample_weather_data.base_time


def test_cache_not_found(clean_cache_dir):
    """캐시 파일이 없을 때 None 반환 테스트"""
    loaded_data = load_weather_cache()
    assert loaded_data is None
    
    last_success = load_last_success_cache()
    assert last_success is None


def test_weather_data_to_dict(sample_weather_data):
    """WeatherData to dict 변환 테스트"""
    data_dict = sample_weather_data.to_dict()
    
    assert isinstance(data_dict, dict)
    assert data_dict["message"] == sample_weather_data.message
    assert data_dict["temp"] == sample_weather_data.temp
    assert data_dict["base_date"] == sample_weather_data.base_date


def test_weather_data_from_dict(sample_weather_data):
    """dict to WeatherData 변환 테스트"""
    data_dict = sample_weather_data.to_dict()
    reconstructed = WeatherData.from_dict(data_dict)
    
    assert reconstructed.message == sample_weather_data.message
    assert reconstructed.temp == sample_weather_data.temp
    assert reconstructed.base_date == sample_weather_data.base_date


def test_clear_old_caches(clean_cache_dir):
    """오래된 캐시 삭제 테스트"""
    # 오래된 캐시 파일 생성 (7일 이상 지난 것)
    old_date = "20250101"
    old_cache_path = CACHE_DIR / f"{old_date}_0500.json"
    old_cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    old_data = {
        "message": "old message",
        "temp": "10",
        "weather_status": "흐림",
        "pop": "20",
        "base_date": old_date,
        "base_time": "0500",
        "cached_at": "2025-01-01T05:12:00+09:00"
    }
    
    with open(old_cache_path, "w", encoding="utf-8") as f:
        json.dump(old_data, f)
    
    # 현재 캐시 파일 생성
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    today = now.strftime("%Y%m%d")
    current_cache_path = CACHE_DIR / f"{today}_0500.json"
    
    current_data = {
        "message": "current message",
        "temp": "15",
        "weather_status": "맑음",
        "pop": "10",
        "base_date": today,
        "base_time": "0500",
        "cached_at": now.isoformat()
    }
    
    with open(current_cache_path, "w", encoding="utf-8") as f:
        json.dump(current_data, f)
    
    # 정리 실행
    clear_old_caches()
    
    # 오래된 캐시는 삭제되고 현재 캐시는 남아있어야 함
    assert not old_cache_path.exists()
    assert current_cache_path.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
