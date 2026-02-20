import asyncio
import logging
import sys
import os
import pprint

# 프로젝트 루트를 경로에 추가
sys.path.append('/app')

from backend.services.news.esports_results import _fetch

async def find_real_lec():
    # 1. 이름에 'LEC'가 들어간 모든 리그 검색 (최대 50개)
    leagues = await _fetch('/leagues', {'search[name]': 'LEC', 'per_page': 50})
    
    results = []
    for l in leagues:
        results.append({
            'id': l.get('id'),
            'name': l.get('name'),
            'slug': l.get('slug'),
            'videogame': l.get('videogame', {}).get('slug')
        })
    
    print("--- LEC 검색 결과 ---")
    pprint.pprint(results)

if __name__ == "__main__":
    asyncio.run(find_real_lec())
