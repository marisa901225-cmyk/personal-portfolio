import asyncio
import logging
import sys
import os

# 프로젝트 루트(/app)를 경로에 추가
sys.path.append('/app')

from backend.services.news.esports_monitor import EsportsMonitor
from backend.core.db import SessionLocal
from backend.core.models import EsportsMatch

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_lec_fetch():
    monitor = EsportsMonitor(dry_run=True)
    db = SessionLocal()
    try:
        logger.info("LEC 경기 수집 테스트 시작...")
        # 1. API에서 직접 데이터 가져와보기
        api_game = "lol"
        matches = await monitor._fetch(
            f"/{api_game}/matches/upcoming",
            {"per_page": 50, "sort": "begin_at"}
        )
        
        logger.info(f"PandaScore에서 {len(matches)}개의 LoL 경기를 가져왔습니다.")
        for m in matches:
            league_name = (m.get("league") or {}).get("name") or ""
            if "LEC" in league_name:
                logger.info(f"🔍 LEC 경기 발견: {m.get('name')} (League: {league_name})")
        
        # 2. 인덱싱 실행
        await monitor._index_upcoming_matches(db)
        
        # 3. DB 확인
        lec_matches = db.query(EsportsMatch).filter(EsportsMatch.name.like('%LEC%')).all()
        if lec_matches:
            logger.info(f"성공! {len(lec_matches)}개의 LEC 경기가 DB에 있습니다.")
        else:
            logger.warning("DB에서 LEC 경기를 찾지 못했습니다.")
            
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test_lec_fetch())
