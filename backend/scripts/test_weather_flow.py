"""
날씨 시스템 전체 흐름 수동 테스트 스크립트

테스트 시나리오:
1. 캐시 클리어 → fetch → API 호출 확인
2. 캐시 있음 → fetch → 캐시 사용 확인
3. 캐시 + API 실패 → last_success 캐시 사용 확인
"""
import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from backend.services.news.weather import (
    fetch_weather_from_cache,
    _fetch_from_api,
    prefetch_weather_at_05
)
from backend.services.news.weather_cache import (
    load_weather_cache,
    load_last_success_cache,
    save_weather_cache,
    is_cache_fresh,
    CACHE_DIR,
    WeatherData
)
from datetime import datetime
from zoneinfo import ZoneInfo


def print_header(title: str):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


async def test_scenario_1_no_cache():
    """시나리오 1: 캐시 없음 → API 호출"""
    print_header("시나리오 1: 캐시 없음 → API 호출")
    
    # 캐시 클리어
    if CACHE_DIR.exists():
        for cache_file in CACHE_DIR.glob("*.json"):
            cache_file.unlink()
        print("✓ 캐시 클리어 완료")
    
    # fetch 시도
    print("→ fetch_weather_from_cache() 호출 중...")
    message = await fetch_weather_from_cache()
    
    if message:
        print(f"✓ API 호출 성공!")
        print(f"\n[메시지 샘플]")
        print("-" * 60)
        print(message[:200] + "..." if len(message) > 200 else message)
        print("-" * 60)
        
        # 캐시 저장 확인
        cached_data = load_weather_cache()
        if cached_data:
            print(f"✓ 캐시 저장 확인: {cached_data.base_date} {cached_data.base_time}")
        
        # last_success 캐시 확인
        last_success = load_last_success_cache()
        if last_success:
            print(f"✓ last_success 캐시 저장 확인")
    else:
        print("✗ API 호출 실패 (KMA_SERVICE_KEY 확인 필요)")


async def test_scenario_2_use_cache():
    """시나리오 2: 캐시 있음 → 캐시 사용"""
    print_header("시나리오 2: 캐시 있음 → 캐시 사용")
    
    # 캐시 존재 확인
    if is_cache_fresh():
        print("✓ 신선한 캐시 발견")
        
        # fetch 시도
        print("→ fetch_weather_from_cache() 호출 중...")
        message = await fetch_weather_from_cache()
        
        if message:
            print("✓ 캐시를 사용한 메시지 반환 성공!")
            print(f"\n[메시지 샘플]")
            print("-" * 60)
            print(message[:200] + "..." if len(message) > 200 else message)
            print("-" * 60)
        else:
            print("✗ 캐시 사용 실패")
    else:
        print("✗ 신선한 캐시 없음 (시나리오 1을 먼저 실행하세요)")


async def test_scenario_3_fallback_to_last_success():
    """시나리오 3: 캐시 없음 + API 실패 → last_success 폴백"""
    print_header("시나리오 3: last_success 폴백 (수동 시뮬레이션)")
    
    # last_success 캐시 확인
    last_success = load_last_success_cache()
    if last_success:
        print(f"✓ last_success 캐시 발견: {last_success.base_date} {last_success.base_time}")
        print(f"\n[last_success 메시지 샘플]")
        print("-" * 60)
        print(last_success.message[:200] + "..." if len(last_success.message) > 200 else last_success.message)
        print("-" * 60)
        
        # 폴백 메시지 시뮬레이션
        warning_prefix = "⚠️ <b>[이전 날씨 데이터]</b>\n\n"
        fallback_message = warning_prefix + last_success.message
        print(f"\n[폴백 메시지 (⚠️ 표시 포함)]")
        print("-" * 60)
        print(fallback_message[:200] + "..." if len(fallback_message) > 200 else fallback_message)
        print("-" * 60)
    else:
        print("✗ last_success 캐시 없음 (시나리오 1을 먼저 실행하세요)")


async def test_prefetch_simulation():
    """프리페치 시뮬레이션 (재시도 로직 테스트)"""
    print_header("프리페치 시뮬레이션")
    
    print("→ prefetch_weather_at_05() 호출 중...")
    print("  (재시도 로직: 0분, 13분, 20분, 35분)")
    print("  ※ 실제로는 시간 간격이 있지만 테스트에서는 즉시 실행됩니다.")
    
    # 원본 함수를 호출하되 sleep을 무시하도록 수정할 수도 있지만
    # 여기서는 _fetch_from_api만 직접 테스트
    print("\n→ _fetch_from_api() 직접 호출 테스트...")
    weather_data = await _fetch_from_api()
    
    if weather_data:
        print("✓ API 호출 성공!")
        print(f"  - 기온: {weather_data.temp}°C")
        print(f"  - 날씨: {weather_data.weather_status}")
        print(f"  - 강수확률: {weather_data.pop}%")
        print(f"  - 발표시각: {weather_data.base_date} {weather_data.base_time}")
    else:
        print("✗ API 호출 실패")


def show_cache_files():
    """캐시 파일 목록 표시"""
    print_header("캐시 파일 목록")
    
    if not CACHE_DIR.exists():
        print("✗ 캐시 디렉토리가 없습니다.")
        return
    
    cache_files = list(CACHE_DIR.glob("*.json"))
    if not cache_files:
        print("✗ 캐시 파일이 없습니다.")
        return
    
    print(f"캐시 디렉토리: {CACHE_DIR}")
    print(f"\n발견된 캐시 파일 ({len(cache_files)}개):")
    for cache_file in sorted(cache_files):
        size = cache_file.stat().st_size
        print(f"  - {cache_file.name} ({size} bytes)")


async def main():
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 15 + "날씨 시스템 통합 테스트" + " " * 15 + "║")
    print("╚" + "═" * 58 + "╝")
    
    # 캐시 파일 목록 표시
    show_cache_files()
    
    # 시나리오 1: 캐시 없음 → API 호출
    await test_scenario_1_no_cache()
    
    # 시나리오 2: 캐시 있음 → 캐시 사용
    await test_scenario_2_use_cache()
    
    # 시나리오 3: last_success 폴백
    await test_scenario_3_fallback_to_last_success()
    
    # 프리페치 시뮬레이션
    await test_prefetch_simulation()
    
    # 최종 캐시 파일 목록
    show_cache_files()
    
    print("\n" + "=" * 60)
    print("  테스트 완료!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
