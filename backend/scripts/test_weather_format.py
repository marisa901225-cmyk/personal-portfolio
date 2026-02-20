"""
날짜 포맷 테스트
"""
import asyncio
import sys
from pathlib import Path

# 프로젝트 루트 추가
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from backend.services.news.weather import _fetch_from_api

async def test():
    print("날씨 API 호출 테스트...")
    print("-" * 60)
    
    data = await _fetch_from_api()
    
    if data:
        print(f"✓ API 호출 성공!\n")
        print(f"발표시각: {data.base_date} {data.base_time}")
        print(f"\n[생성된 메시지]")
        print("-" * 60)
        print(data.message)
        print("-" * 60)
    else:
        print("✗ API 호출 실패")

if __name__ == "__main__":
    asyncio.run(test())
