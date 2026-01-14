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

        interest_keywords = [
            "LCK", "LPL", "LEC", "LCS", "Worlds", "MSI", "월즈", 
            "Challengers", "CL", "Pacific", "VCT", "Masters", "Champions"
        ]
        
        exclude_keywords = [".A", "Academy", "Youth", "Secondary", "Secondary", "아카데미"]

        count = 0
        for match in matches:
            name = match.get("name", "")
            game_info = match.get("videogame", {})
            game_name = game_info.get("name", "").lower()
            league = match.get("league", {}).get("name", "Unknown League")
            begin_at_str = match.get("begin_at")
            if not begin_at_str: continue

            # 1. 종목 필터링 (완전 일치 또는 명확한 포함 관계)
            # 'King of Glory' 등을 방지하기 위해 'League of Legends'와 'Valorant'만 허용
            is_lol = "league of legends" == game_name
            is_valorant = "valorant" == game_name
            
            if not (is_lol or is_valorant):
                continue

            # 2. 관심 리그/대회 필터링
            full_text = f"{name} {league}"
            # KPL(왕자영요) 등이 LPL과 헷갈리지 않도록 단어 단위 혹은 대문자 매칭 권장
            is_interesting = any(kw in full_text for kw in interest_keywords)
            
            # 3. 2군/아카데미 팀 필터링 (.A, Academy 등)
            # 단, LCK나 CL(Challengers) 관련은 본인 등판이므로 허용
            is_lck_cl = any(kw in full_text for kw in ["LCK", "Challengers", "CL"])
            is_academy = any(ex in full_text for ex in exclude_keywords)
            
            if not is_interesting:
                continue
                
            if is_academy and not is_lck_cl:
                # 국내 챌린저스가 아닌 타 지역 아카데미 팀은 스킵
                continue
            
            begin_at_utc = datetime.fromisoformat(begin_at_str.replace("Z", "+00:00"))
            # PandaScore는 UTC로 제공되므로 한국 시간(KST, UTC+9)으로 변환하여 저장
            begin_at = begin_at_utc + timedelta(hours=9)
            
            game = "LoL" if is_lol else "Valorant"
            
            # 리그 및 국제대회 태깅
            league_name = match.get("league", {}).get("name", "")
            league_tag = "기타"
            is_international = False
            
            lower_league = league_name.lower()
            if "lck" in lower_league:
                league_tag = "LCK"
            elif "challengers korea" in lower_league or "lck cl" in lower_league:
                league_tag = "LCK-CL"
            elif "lpl" in lower_league:
                league_tag = "LPL"
            elif "lec" in lower_league:
                league_tag = "LEC"
            elif "lcs" in lower_league:
                league_tag = "LCS"
            elif any(kw in lower_league for kw in ["worlds", "msi", "mid-season invitational"]):
                league_tag = "Worlds/MSI"
                is_international = True
            elif any(kw in lower_league for kw in ["champions", "masters", "vct"]):
                league_tag = "VCT"
                is_international = True
            
            title = f"[Esports Schedule] {game} - {name}"
            content = f"Match: {name}\nLeague: {league}\nTournament: {match.get('tournament', {}).get('name')}\nStart Time: {begin_at_str}\nLink: {match.get('official_stream_url', '')}"
            
            content_hash = calculate_simhash(title + content)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing:
                continue

            news = GameNews(
                content_hash=content_hash,
                game_tag=game,
                league_tag=league_tag,
                is_international=is_international,
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
