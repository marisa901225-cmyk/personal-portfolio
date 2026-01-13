import logging
import httpx
import os
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from ...core.models import GameNews
from .core import calculate_simhash, PANDASCORE_URL

logger = logging.getLogger(__name__)

async def collect_pandascore_schedules(db: Session):
    """
    PandaScore API를 사용하여 향후 e스포츠 경기 일정을 수집한다.
    """
    api_key = os.getenv("PANDASCORE_API_KEY")
    if not api_key:
        logger.warning("PANDASCORE_API_KEY not set. Skipping PandaScore collection.")
        return

    logger.info("Collecting PandaScore upcoming esports matches...")
    url = f"{PANDASCORE_URL}/matches/upcoming"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params={"per_page": 100}, timeout=20.0)
            response.raise_for_status()
            matches = response.json()

        count = 0
        for match in matches:
            name = match.get("name")
            game = match.get("videogame", {}).get("name", "Unknown Game")
            league = match.get("league", {}).get("name", "Unknown League")
            begin_at_str = match.get("begin_at")
            if not begin_at_str: continue
            
            begin_at_utc = datetime.fromisoformat(begin_at_str.replace("Z", "+00:00"))
            # PandaScore는 UTC로 제공되므로 한국 시간(KST, UTC+9)으로 변환하여 저장
            begin_at = begin_at_utc + timedelta(hours=9)
            
            title = f"[Esports Schedule] {game} - {name}"
            content = f"Match: {name}\nLeague: {league}\nTournament: {match.get('tournament', {}).get('name')}\nStart Time: {begin_at_str}\nLink: {match.get('official_stream_url', '')}"

            content_hash = calculate_simhash(title + content)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing:
                continue

            news = GameNews(
                content_hash=content_hash,
                game_tag=game,
                source_name="PandaScore",
                source_type="schedule",
                event_time=begin_at,
                title=title,
                full_content=content,
                published_at=datetime.now(timezone.utc)
            )
            db.add(news)
            count += 1

        db.commit()
        logger.info(f"Collected {count} PandaScore match schedules.")
    except Exception as e:
        logger.error(f"Failed to collect PandaScore schedules: {e}")
