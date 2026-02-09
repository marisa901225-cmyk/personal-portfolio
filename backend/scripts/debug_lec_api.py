import asyncio
import logging
import sys
import os
import pprint

# 프로젝트 루트를 경로에 추가
sys.path.append('/app')

from backend.services.news.esports_results import _fetch, _get_league_id, _format_match, fetch_lec_results_summary
from backend.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_lec_api():
    logger.info("LEC API 정밀 디버깅 시작...")
    
    # 진짜 LEC ID: 4197 (League of Legends LEC)
    league_id = 4197
    logger.info(f"조정된 LEC League ID: {league_id}")
    
    if not league_id:
        logger.error("LEC League ID를 가져오지 못했습니다.")
        return

    # 2. 최근 종료된 경기 목록 조회 (필터링 없이)
    logger.info("최근 종료된 경기 5개 조회 중...")
    try:
        matches = await _fetch(
            "/matches",
            {
                "filter[league_id]": league_id,
                "filter[status]": "finished",
                "sort": "-end_at",
                "per_page": 5,
            },
        )
        logger.info(f"수집된 경기 수: {len(matches)}")
        for m in matches:
            formatted = _format_match(m, compact=False)
            logger.info(f" - 경기: {formatted}")
            logger.info(f"   종료시각(UTC): {m.get('end_at')}")
            
    except Exception as e:
        logger.error(f"API 호출 중 오류 발생: {e}")

    # 3. 요약 함수 테스트 (24시간 이내)
    summary = await fetch_lec_results_summary(limit=10, lookback_hours=48) # 넉넉하게 48시간
    logger.info(f"최종 요약 결과 (48시간 기준): {summary if summary else '결과 없음'}")

if __name__ == "__main__":
    asyncio.run(debug_lec_api())
