import logging
import feedparser
import re
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log
from sqlalchemy.orm import Session
from urllib.parse import quote
from ...core.models import GameNews
from ...core.time_utils import utcnow
from .core import (
    GOOGLE_NEWS_MACRO_QUERIES,
    prepare_news_ingest_record,
    persist_news_record,
)
from ..duckdb_refine_config import get_db_path

logger = logging.getLogger(__name__)


def _infer_rss_metadata(source_name: str, title: str) -> tuple[str, str | None]:
    source = str(source_name or "").lower()
    normalized_title = str(title or "").lower()

    if "inven lol" in source or any(keyword in normalized_title for keyword in ("롤", "lol", "lck", "lec", "lpl")):
        return "LoL", "Esports"
    if "review" in source or "리뷰" in source:
        return "Gaming", "Review"
    if "ranking" in source or "순위" in source or "분석" in source:
        return "Gaming", "Ranking"
    if "intro" in source or "소개" in source:
        return "Gaming", "Preview"
    return "General", None


def load_recent_inven_game_digest(
    *,
    db_path: str | None = None,
    now: datetime | None = None,
    lookback_days: int = 7,
    limit: int = 4,
) -> str:
    """최근 Inven 게임소개/리뷰/순위분석 기사를 브리핑용으로 압축한다."""
    db_file = db_path or get_db_path()
    if not db_file:
        return ""

    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    since = base - timedelta(days=max(1, int(lookback_days)))
    since_str = since.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    until_str = base.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    sql = """
        SELECT source_name, title, published_at
        FROM game_news
        WHERE source_type = 'news'
          AND source_name IN ('Inven Game Intro', 'Inven Game Review', 'Inven Ranking Analysis')
          AND datetime(published_at) >= datetime(?)
          AND datetime(published_at) <= datetime(?)
        ORDER BY datetime(published_at) DESC, id DESC
        LIMIT ?
    """

    try:
        with sqlite3.connect(db_file) as conn:
            rows = list(conn.execute(sql, (since_str, until_str, max(1, int(limit)))))
    except Exception as exc:
        logger.error("Failed to load recent Inven game digest: %s", exc, exc_info=True)
        return ""

    if not rows:
        return ""

    label_map = {
        "Inven Game Intro": "소개",
        "Inven Game Review": "리뷰",
        "Inven Ranking Analysis": "순위분석",
    }
    items: list[str] = []
    for source_name, title, published_at in rows:
        label = label_map.get(str(source_name or "").strip(), "게임기사")
        time_label = str(published_at or "").strip()[:16].replace("T", " ")
        prefix = f"{time_label} " if time_label else ""
        items.append(f"{prefix}[{label}] {title}")

    return "최근 Inven 게임 기사: " + " | ".join(items)


def collect_rss(db: Session, feed_url: str, source_name: str):
    """
    RSS 피드에서 뉴스 수집 및 저장
    """
    try:
        feed = feedparser.parse(feed_url)
        recent_limit = datetime.now(timezone.utc) - timedelta(hours=48)
        recent_news = db.query(GameNews).filter(GameNews.published_at >= recent_limit).all()
        for entry in feed.entries:
            title = entry.title
            link = entry.link
            description = getattr(entry, 'description', '')
            
            # HTML 태그 제거
            clean_desc = re.sub('<[^<]+?>', '', description)
            
            # 날짜 파싱 (RSS 파싱 결과 활용)
            try:
                from time import mktime
                published_at = datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
            except Exception:
                published_at = datetime.now(timezone.utc)

            # 너무 오래된 기사 제외 (최근 14일)
            if published_at < datetime.now(timezone.utc) - timedelta(days=14):
                continue
            
            content_hash, _recent_news, should_skip = prepare_news_ingest_record(
                db,
                title=title,
                content=clean_desc,
                published_at=published_at,
                recent_window_hours=48,
                recent_news=recent_news,
            )
            if should_skip:
                continue
            
            game_tag, category_tag = _infer_rss_metadata(source_name, title)
            if "발로란트" in title:
                game_tag = "Valorant"
                category_tag = "Esports"
            
            # DB 저장
            news = persist_news_record(
                db,
                model_cls=GameNews,
                content_hash=content_hash,
                game_tag=game_tag,
                category_tag=category_tag,
                source_name=source_name,
                title=title,
                url=link,
                full_content=clean_desc,
                published_at=published_at,
            )
            recent_news.append(news)
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

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
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
        async with httpx.AsyncClient() as client:
            response = await client.get(feed_url, timeout=15.0)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        
        clean_desc = "" # Initialize here to prevent NameError
        count = 0
        recent_limit = datetime.now(timezone.utc) - timedelta(hours=48)
        recent_news = db.query(GameNews).filter(GameNews.published_at >= recent_limit).all()
        
        for entry in feed.entries[:20]:  # 쿼리당 최대 20개
            title = entry.get("title", "")
            link = entry.get("link", "")
            published_str = entry.get("published", "")
            
            # 본문 추출 (RSS는 요약 정보만 제공하는 경우가 많음)
            description = entry.get("summary", "") or entry.get("description", "")
            clean_desc = re.sub('<[^<]+?>', '', description) if description else ""
            
            # 날짜 파싱
            try:
                from email.utils import parsedate_to_datetime
                published_at = parsedate_to_datetime(published_str)
            except Exception:
                published_at = datetime.now(timezone.utc)
            
            # 너무 오래된 기사 제외 (최근 14일)
            if published_at < datetime.now(timezone.utc) - timedelta(days=14):
                continue
            
            content_hash, recent_news, should_skip = prepare_news_ingest_record(
                db,
                title=title,
                content=clean_desc,
                published_at=published_at,
                recent_window_hours=48,
                recent_news=recent_news,
            )
            if should_skip:
                continue
            
            # game_tag 설정
            game_tag = f"GlobalMacro-{region}"
            
            news = persist_news_record(
                db,
                model_cls=GameNews,
                content_hash=content_hash,
                game_tag=game_tag,
                category_tag="",
                source_name="GoogleNews",
                title=title,
                url=link,
                full_content="",  # RSS에서는 본문 미제공
                published_at=published_at,
            )
            recent_news.append(news)
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
