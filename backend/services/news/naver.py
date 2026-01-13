import logging
import httpx
import os
import re
import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from ...core.models import GameNews
from .core import calculate_simhash, NAVER_NEWS_URL, NAVER_ESPORTS_QUERIES, NAVER_ECONOMY_QUERIES

logger = logging.getLogger(__name__)

async def collect_naver_news(db: Session, query: str, category: str = "esports"):
    """
    네이버 뉴스 검색 API를 사용하여 뉴스를 수집한다.
    """
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        logger.warning("NAVER_CLIENT_ID or NAVER_CLIENT_SECRET not set. Skipping Naver news collection.")
        return 0
    
    logger.info(f"Collecting Naver news for query: '{query}' (category: {category})")
    
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {
        "query": query,
        "display": 100,  # 최대 100까지 가능
        "start": 1,
        "sort": "date",  # 최신순
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                NAVER_NEWS_URL, 
                headers=headers, 
                params=params, 
                timeout=15.0
            )
            response.raise_for_status()
            data = response.json()
        
        items = data.get("items", [])
        count = 0
        
        for item in items:
            title = item.get("title", "")
            description = item.get("description", "")
            link = item.get("link", "")
            original_link = item.get("originallink", "")
            pub_date_str = item.get("pubDate", "")
            
            # HTML 태그 제거 (<b>, </b> 등)
            clean_title = re.sub(r'<[^>]+>', '', title)
            clean_desc = re.sub(r'<[^>]+>', '', description)
            
            # 날짜 파싱 (RFC 2822 형식: "Fri, 09 Jan 2026 10:30:00 +0900")
            try:
                from email.utils import parsedate_to_datetime
                published_at = parsedate_to_datetime(pub_date_str)
            except Exception:
                published_at = datetime.now(timezone.utc)
            
            # 중복 체크 (SimHash)
            content_hash = calculate_simhash(clean_title + clean_desc)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing:
                continue
            
            # game_tag 결정 (검색어 기반)
            if category == "esports":
                game_tag = "Esports"
                # 세부 분류
                q_lower = query.lower()
                if "lol" in q_lower or "롤" in q_lower or "lck" in q_lower or "월즈" in q_lower:
                    game_tag = "LoL"
                elif "vct" in q_lower or "발로" in q_lower or "퍼시픽" in q_lower:
                    game_tag = "Valorant"
                elif "챌린저스" in q_lower or "2군" in q_lower or "ck" in q_lower:
                    game_tag = "LCK-CK"
            else:
                game_tag = "Economy"
                # 세부 분류
                if "삼성" in query or "반도체" in query or "hbm" in query.lower():
                    game_tag = "Tech/Semiconductor"
                elif "환율" in query or "달러" in query:
                    game_tag = "FX"
                elif "fomc" in query.lower() or "연준" in query:
                    game_tag = "Fed/Macro"
            
            news = GameNews(
                content_hash=content_hash,
                game_tag=game_tag,
                source_name="Naver",
                source_type="news",
                title=clean_title,
                url=original_link or link,
                full_content=clean_desc,
                published_at=published_at,
            )
            db.add(news)
            count += 1
        
        db.commit()
        logger.info(f"Collected {count} Naver news for '{query}'")
        return count
        
    except httpx.HTTPStatusError as e:
        logger.error(f"Naver API HTTP error: {e.response.status_code} - {e.response.text}")
        return 0
    except Exception as e:
        logger.error(f"Failed to collect Naver news for '{query}': {e}")
        return 0

async def collect_all_naver_news(db: Session):
    """
    모든 네이버 뉴스 검색 버킷을 순회하며 수집한다.
    """
    logger.info("Starting Naver News collection for all buckets...")
    total_count = 0
    
    # E스포츠 버킷
    for query in NAVER_ESPORTS_QUERIES:
        count = await collect_naver_news(db, query, category="esports")
        total_count += count
        await asyncio.sleep(0.3)  # Rate limit 방지
    
    # 경제 버킷
    for query in NAVER_ECONOMY_QUERIES:
        count = await collect_naver_news(db, query, category="economy")
        total_count += count
        await asyncio.sleep(0.3)
    
    logger.info(f"Naver News collection completed. Total: {total_count} articles.")
    return total_count
