"""
Google News RSS를 사용한 뉴스 수집 서비스.
해외 종목/지수 관련 뉴스는 네이버보다 구글 뉴스가 더 정확함.

동작 방식:
1. 원문(영문/한글)은 full_content에 그대로 저장
2. 영문 뉴스인 경우 LLM으로 한국어 요약 생성 → summary 컬럼에 저장
3. 사용자는 요약 보고 관심 있으면 원문 링크로 직접 가서 번역기 사용
"""
import logging
import httpx
import re
import asyncio
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree
from urllib.parse import quote
from sqlalchemy.orm import Session
from ...core.models import GameNews, SpamNews
from .core import (
    GOOGLE_NEWS_MACRO_QUERIES,
    determine_news_tags,
    detect_ad_keyword,
    is_blocked_google_source,
    prepare_news_ingest_record,
    persist_news_record,
)

logger = logging.getLogger(__name__)

# Google News RSS URL 템플릿
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"


def _summarize_english_article(title: str, content: str, ticker: str = None) -> str:
    """
    영문 뉴스를 한국어로 요약한다 (EXAONE 1.2B 사용).
    원문은 별도로 보존되므로, 여기서는 요약만 생성.
    """
    try:
        from ..llm_service import LLMService
        llm = LLMService.get_instance()
        
        if not llm.is_loaded():
            logger.warning("LLM not loaded, skipping summarization")
            return None
        
        # 티커 정보 포함해서 문맥 제공
        ticker_hint = f"종목: {ticker}" if ticker else ""
        
        messages = [
            {
                "role": "system",
                "content": "당신은 금융 뉴스 번역/요약 전문가입니다. 영문 뉴스를 한국어로 간결하게 요약해주세요. 핵심 내용만 2-3문장으로 전달하세요."
            },
            {
                "role": "user",
                "content": f"""{ticker_hint}
제목: {title}
내용: {content[:500]}

위 영문 뉴스를 한국어로 2-3문장으로 요약해주세요."""
            }
        ]
        
        summary = llm.generate_chat(messages, max_tokens=200, temperature=0.3)
        
        if summary and len(summary) > 10:
            logger.info(f"Summarized: {title[:30]}... -> {summary[:50]}...")
            return summary
        else:
            return None
            
    except Exception as e:
        logger.error(f"Failed to summarize article: {e}")
        return None


def _is_english_content(text: str) -> bool:
    """
    텍스트가 영문인지 판별한다.
    한글이 거의 없으면 영문으로 간주.
    """
    if not text:
        return False
    
    korean_chars = len(re.findall(r'[가-힣]', text))
    total_chars = len(text.strip())
    
    # 한글 비율이 10% 미만이면 영문으로 간주
    return korean_chars / max(total_chars, 1) < 0.1


async def collect_google_news(
    db: Session, 
    query: str, 
    category: str = "economy", 
    hl: str = "en", 
    gl: str = "US",
    summarize_english: bool = False,
    ticker: str = None
):
    """
    구글 뉴스 RSS를 사용하여 뉴스를 수집한다.
    
    Args:
        db: 데이터베이스 세션
        query: 검색어
        category: 카테고리 (economy, esports 등)
        hl: 언어 코드 (en, ko 등)
        gl: 지역 코드 (US, KR 등)
        summarize_english: 영문 뉴스를 LLM으로 요약할지 여부
        ticker: 종목 티커 (요약 시 컨텍스트 제공용)
    """
    # Google News RSS URL 구성
    encoded_query = quote(query)
    url = f"{GOOGLE_NEWS_RSS_URL}?q={encoded_query}&hl={hl}&gl={gl}&ceid={gl}:{hl}"
    
    logger.info(f"Collecting Google News: query='{query}' (hl={hl}, gl={gl}, summarize={summarize_english})")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0, follow_redirects=True)
            response.raise_for_status()
            content = response.text
        
        # RSS XML 파싱
        root = ElementTree.fromstring(content)
        channel = root.find("channel")
        if channel is None:
            logger.warning(f"No channel found in Google News RSS for '{query}'")
            return 0
        
        items = channel.findall("item")
        recent_limit = datetime.now(timezone.utc) - timedelta(days=7)
        recent_news = db.query(GameNews).filter(GameNews.published_at >= recent_limit).all()
        # 현재 배치에서 이미 처리된 해시/제목 추적
        seen_in_batch = set()
        
        count = 0
        
        for item in items:
            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_date_elem = item.find("pubDate")
            description_elem = item.find("description")
            source_elem = item.find("source")
            
            title = title_elem.text if title_elem is not None else ""
            link = link_elem.text if link_elem is not None else ""
            description = description_elem.text if description_elem is not None else ""
            source_name = source_elem.text if source_elem is not None else "Google News"
            pub_date_str = pub_date_elem.text if pub_date_elem is not None else ""

            if is_blocked_google_source(source_name):
                continue
            
            # HTML 태그 제거 (description에서)
            clean_desc = re.sub(r'<[^>]+>', '', description) if description else ""
            game_tag, category_tag, is_international = determine_news_tags(
                category=category,
                query=query,
                title=title,
                description=clean_desc,
                gl=gl,
            )
            
            # 날짜 파싱 (RFC 2822 형식)
            try:
                from email.utils import parsedate_to_datetime
                published_at = parsedate_to_datetime(pub_date_str)
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
                recent_window_hours=24 * 7,
                recent_news=recent_news,
                seen_in_batch=seen_in_batch,
            )
            if should_skip:
                continue
            
            # 광고 체크
            spam_reason = detect_ad_keyword(title)
            
            if spam_reason:
                # 스팸 테이블에 저장
                news = SpamNews(
                    content_hash=content_hash,
                    game_tag=game_tag,
                    category_tag=category_tag,
                    is_international=is_international,
                    source_name=f"Google/{source_name}",
                    source_type="news",
                    title=title,
                    url=link,
                    full_content=clean_desc,
                    published_at=published_at,
                    spam_reason=f"Keyword: {spam_reason}",
                    rule_version=1  # 2026.01 기준 버전 1
                )
                db.add(news)
                logger.info(f"Google: Routed ad to SpamNews: {title[:30]}... ({spam_reason})")
            else:
                # 원문 그대로 저장
                news = GameNews(
                    content_hash=content_hash,
                    game_tag=game_tag,
                    category_tag=category_tag,
                    is_international=is_international,
                    source_name=f"Google/{source_name}",
                    source_type="news",
                    title=title,  # 원본 제목 유지
                    url=link,
                    full_content=clean_desc,  # 원문 그대로 저장
                    summary=None,  # 일단 None으로 저장
                    published_at=published_at,
                )
                db.add(news)
                recent_news.append(news)
                seen_in_batch.add(content_hash)
                db.flush()  # ID 생성을 위해 flush

                # 영문 뉴스인 경우 LLM 요약 생성
                if summarize_english and _is_english_content(title + clean_desc):
                    # 동기 함수를 스레드에서 실행
                    summary = await asyncio.get_event_loop().run_in_executor(
                        None,
                        _summarize_english_article,
                        title,
                        clean_desc,
                        ticker
                    )
                    if summary:
                        news.summary = summary

                count += 1
        
        db.commit()
        logger.info(f"Collected {count} Google News articles for '{query}'")
        return count
        
    except httpx.HTTPStatusError as e:
        logger.error(f"Google News RSS HTTP error: {e.response.status_code}")
        return 0
    except ElementTree.ParseError as e:
        logger.error(f"Failed to parse Google News RSS: {e}")
        return 0
    except Exception as e:
        logger.error(f"Failed to collect Google News for '{query}': {e}")
        return 0


async def collect_stock_news_google(db: Session, ticker: str, company_name: str = None):
    """
    특정 종목에 대한 구글 뉴스를 수집한다.
    해외 종목의 경우 영어 + 한국어 뉴스 모두 수집.
    
    Args:
        db: 데이터베이스 세션
        ticker: 종목 티커 (예: NVDA, AAPL)
        company_name: 회사명 (선택, 예: NVIDIA, Apple, 벨로3D)
    """
    total_count = 0
    
    # 1. 영어 뉴스 수집 (더 정확한 해외 정보) + LLM 요약
    en_search_terms = [f"{ticker} stock"]
    if company_name:
        en_search_terms.append(f"{company_name} stock")
    
    for term in en_search_terms[:2]:
        count = await collect_google_news(
            db, term, 
            category="economy", 
            hl="en", 
            gl="US",
            summarize_english=True,  # 영문 → 한국어 요약
            ticker=ticker
        )
        total_count += count
        await asyncio.sleep(0.5)
    
    # 2. 한국어 뉴스 수집 (한국 투자자 대상 뉴스)
    ko_search_terms = []
    if company_name:
        ko_search_terms.append(company_name)  # 예: "벨로3D", "엔비디아"
        ko_search_terms.append(f"{company_name} 주가")
    ko_search_terms.append(f"{ticker} 주식")
    
    for term in ko_search_terms[:2]:
        count = await collect_google_news(
            db, term, 
            category="economy", 
            hl="ko", 
            gl="KR",
            summarize_english=False,  # 한국어는 요약 불필요
            ticker=ticker
        )
        total_count += count
        await asyncio.sleep(0.5)
    
    logger.info(f"Total collected for {ticker}: {total_count} articles (EN+KO)")
    return total_count


async def collect_all_google_macro_news(db: Session):
    """
    모든 구글 뉴스 거시경제 버킷을 순회하며 수집한다.
    """
    logger.info("Starting Google News macro collection...")
    total_count = 0
    
    for region, queries in GOOGLE_NEWS_MACRO_QUERIES.items():
        gl = "US" if region == "US" else "GB"
        hl = "en"
        
        for query in queries:
            count = await collect_google_news(
                db, query, 
                category="economy", 
                hl=hl, 
                gl=gl,
                summarize_english=True  # 매크로 뉴스도 영문이면 요약
            )
            total_count += count
            await asyncio.sleep(0.5)
    
    logger.info(f"Google News macro collection completed. Total: {total_count} articles.")
    return total_count
