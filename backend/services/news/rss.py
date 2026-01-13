import logging
import feedparser
import re
import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from urllib.parse import quote
from ...core.models import GameNews
from .core import calculate_simhash, GOOGLE_NEWS_MACRO_QUERIES

logger = logging.getLogger(__name__)

def collect_rss(db: Session, feed_url: str, source_name: str):
    """
    RSS 피드에서 뉴스 수집 및 저장
    """
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            title = entry.title
            link = entry.link
            description = getattr(entry, 'description', '')
            
            # HTML 태그 제거
            clean_desc = re.sub('<[^<]+?>', '', description)
            
            # 중복 체크 (SimHash)
            content_hash = calculate_simhash(title + clean_desc)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing:
                continue
            
            # 메타데이터 추출 (간단한 예시)
            game_tag = "General"
            if "롤" in title or "LoL" in title:
                game_tag = "LoL"
            elif "발로란트" in title:
                game_tag = "Valorant"
            
            # DB 저장
            news = GameNews(
                content_hash=content_hash,
                game_tag=game_tag,
                source_name=source_name,
                title=title,
                url=link,
                full_content=clean_desc,
                published_at=datetime.utcnow() # 실제로는 entry.published_parsed 파싱 필요
            )
            db.add(news)
            db.commit() # ID 생성을 위해 즉시 커밋
            db.refresh(news)
            
            logger.info(f"Collected news: {title} (ID: {news.id})")
            
            # Vector Store 등록
            try:
                from ..vector_store import VectorStore
                vs = VectorStore.get_instance()
                # 제목 + 본문을 임베딩
                vs.add_texts([f"[{game_tag}] {title}\n{clean_desc}"], [news.id])
            except Exception as e:
                logger.error(f"Failed to add to vector store: {e}")
            
    except Exception as e:
        logger.error(f"Failed to collect RSS from {source_name}: {e}")

async def collect_google_news(db: Session, query: str, region: str = "US"):
    """
    구글 뉴스 RSS로 해외 뉴스 수집 (영문)
    """
    # 지역별 설정
    if region == "EU":
        hl, gl, ceid = "en-GB", "GB", "GB:en"
    else:
        hl, gl, ceid = "en-US", "US", "US:en"
    
    encoded_query = quote(query)
    feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl={hl}&gl={gl}&ceid={ceid}"
    
    logger.info(f"Collecting Google News for query: '{query}' (region: {region})")
    
    try:
        # feedparser는 동기 라이브러리이므로 블로킹 방지를 위해 run_in_executor 사용 고려 가능
        # 하지만 여기서는 간단히 호출
        feed = feedparser.parse(feed_url)
        count = 0
        
        for entry in feed.entries[:20]:  # 쿼리당 최대 20개
            title = entry.get("title", "")
            link = entry.get("link", "")
            published_str = entry.get("published", "")
            
            # 날짜 파싱
            try:
                from email.utils import parsedate_to_datetime
                published_at = parsedate_to_datetime(published_str)
            except Exception:
                published_at = datetime.now(timezone.utc)
            
            # 중복 체크 (SimHash)
            content_hash = calculate_simhash(title)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing:
                continue
            
            # game_tag 설정
            game_tag = f"GlobalMacro-{region}"
            
            news = GameNews(
                content_hash=content_hash,
                game_tag=game_tag,
                source_name="GoogleNews",
                source_type="news",
                title=title,
                url=link,
                full_content="",  # RSS에서는 본문 미제공
                published_at=published_at,
            )
            db.add(news)
            count += 1
        
        db.commit()
        logger.info(f"Collected {count} Google News for '{query}' ({region})")
        return count
        
    except Exception as e:
        logger.error(f"Failed to collect Google News for '{query}': {e}")
        return 0

async def collect_all_google_news(db: Session):
    """
    모든 구글 뉴스 거시경제 키워드를 순회하며 수집한다.
    """
    logger.info("Starting Google News collection for all macro buckets...")
    total_count = 0
    
    for region, queries in GOOGLE_NEWS_MACRO_QUERIES.items():
        for query in queries:
            count = await collect_google_news(db, query, region)
            total_count += count
            await asyncio.sleep(0.5)  # Rate limit 방지
    
    logger.info(f"Google News collection completed. Total: {total_count} articles.")
    return total_count
