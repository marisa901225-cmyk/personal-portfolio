import logging
import httpx
import os
import re
import asyncio
from datetime import datetime, timezone
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from sqlalchemy.orm import Session
from ...core.config import settings
from ...core.models import GameNews, SpamNews
from .core import calculate_simhash, NAVER_NEWS_URL, determine_news_tags

logger = logging.getLogger(__name__)

def _is_ad(title: str) -> str:
    """
    제목이 광고성인지 체크한다.
    광고면 해당 키워드(이유)를 반환하고, 아니면 None을 반환.
    """
    for kw in ["이벤트", "세미나", "기획전", "가이드북", "서포터즈", "참가자 모집", "수강생 모집"]:
        if kw in title:
            return kw
    return None

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError)),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
async def collect_naver_news(db: Session, query: str, category: str = "esports"):
    """
    네이버 뉴스 검색 API를 사용하여 뉴스를 수집한다.
    """
    client_id = settings.naver_client_id
    client_secret = settings.naver_client_secret
    
    if not client_id or not client_secret:
        logger.warning("NAVER_CLIENT_ID or NAVER_CLIENT_SECRET not set. Skipping Naver news collection.")
        return 0
    
    logger.info(f"Collecting Naver news for query: '{query}' (category: {category})")
    count = 0
    
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
        # 최근 7일 내의 뉴스들과 비교하여 중복 판별 (메모리 내 빠른 검색용)
        from datetime import timedelta
        recent_limit = datetime.now(timezone.utc) - timedelta(days=7)
        recent_news = db.query(GameNews).filter(GameNews.published_at >= recent_limit).all()
        
        # 현재 배치에서 이미 처리된 해시/제목 추적
        seen_in_batch = set()
        
        for item in items:
            title = item.get("title", "")
            description = item.get("description", "")
            link = item.get("link", "")
            original_link = item.get("originallink", "")
            pub_date_str = item.get("pubDate", "")
            
            # HTML 태그 제거 (<b>, </b> 등)
            clean_title = re.sub(r'<[^>]+>', '', title)
            clean_desc = re.sub(r'<[^>]+>', '', description)
            
            # 정확한 중복 체크 (해시)
            content_hash = calculate_simhash(clean_title + clean_desc)
            if content_hash in seen_in_batch:
                continue
            
            # 1. DB 전체에서 정확히 일치하는 해시나 제목이 있는지 체크 (인덱스 활용)
            exists = db.query(GameNews.id).filter(
                (GameNews.content_hash == content_hash) | (GameNews.title == clean_title)
            ).first()
            if exists:
                seen_in_batch.add(content_hash)
                continue
            
            # 날짜 파싱 (RFC 2822 형식)
            try:
                from email.utils import parsedate_to_datetime
                published_at = parsedate_to_datetime(pub_date_str)
            except Exception:
                published_at = datetime.now(timezone.utc)
            
            # 너무 오래된 기사 제외 (최근 14일 이내만 수시 수집)
            if published_at < datetime.now(timezone.utc) - timedelta(days=14):
                continue
            
            # 2. 유사도 기반 중복 체크 (최근 7일 데이터와 비교)
            from .core import is_duplicate_complex
            if is_duplicate_complex(clean_title, content_hash, recent_news):
                seen_in_batch.add(content_hash)
                continue
            
            game_tag, category_tag, _is_international = determine_news_tags(
                category=category,
                query=query,
                title=clean_title,
                description=clean_desc,
                gl="KR",
            )
            
            # 광고 체크
            spam_reason = _is_ad(clean_title)
            
            if spam_reason:
                # 스팸 테이블에 저장
                news = SpamNews(
                    content_hash=content_hash,
                    game_tag=game_tag,
                    category_tag=category_tag,
                    source_name="Naver",
                    source_type="news",
                    title=clean_title,
                    url=original_link or link,
                    full_content=clean_desc,
                    published_at=published_at,
                    spam_reason=f"Keyword: {spam_reason}",
                    rule_version=1  # 2026.01 기준 버전 1
                )
                db.add(news)
                logger.info(f"Naver: Routed ad to SpamNews: {clean_title[:30]}... ({spam_reason})")
            else:
                news = GameNews(
                    content_hash=content_hash,
                    game_tag=game_tag,
                    category_tag=category_tag,
                    source_name="Naver",
                    source_type="news",
                    title=clean_title,
                    url=original_link or link,
                    full_content=clean_desc,
                    published_at=published_at,
                )
                db.add(news)
                recent_news.append(news)
                seen_in_batch.add(content_hash)
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
    from .core import load_naver_queries
    esports_queries, economy_queries = load_naver_queries()
    
    logger.info("Starting Naver News collection for all buckets...")
    total_count = 0
    
    # E스포츠 버킷
    for query in esports_queries:
        count = await collect_naver_news(db, query, category="esports")
        total_count += count
        await asyncio.sleep(0.3)  # Rate limit 방지
    
    # 경제 버킷
    for query in economy_queries:
        count = await collect_naver_news(db, query, category="economy")
        total_count += count
        await asyncio.sleep(0.3)
    
    logger.info(f"Naver News collection completed. Total: {total_count} articles.")
    return total_count
