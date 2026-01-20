from __future__ import annotations

import logging
import re
from typing import List, Optional, Dict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.models_misc import GameNews
from .news.naver import collect_naver_news
from .news.google import collect_stock_news_google

logger = logging.getLogger(__name__)

def clean_asset_name(name: str) -> str:
    """종목명에서 불필요한 수식어나 브랜드명을 제거하여 검색 성능을 높인다."""
    # ETF 관련 수식어 및 해외 기업 접미사 제거
    name = re.sub(r'(ACE|KODEX|TIGER|RISE|SOL|HANARO|KBSTAR|PLUS|Ultra|ProShares|ETF|Plus|Ltd|Inc|Corp|Group|Holding)', '', name, flags=re.IGNORECASE)
    # 괄호 및 특수문자 제거
    name = re.sub(r'[\(\)\[\]]', ' ', name)
    # 불필요한 공백 정리
    name = " ".join(name.split()).strip()
    return name

def extract_market_keywords(name: str) -> List[str]:
    """종목명에서 시장 지수나 핵심 산업 키워드를 추출한다."""
    keywords = []
    # 주요 지수 패턴
    indices = ["S&P500", "나스닥100", "NASDAQ100", "코스피200", "KOSPI200", "반도체", "2차전지", "전기차", "빅테크"]
    for idx in indices:
        if idx.lower() in name.lower():
            keywords.append(idx)
    return keywords

def is_foreign_stock(ticker: str, query: str) -> bool:
    """
    해외 종목인지 판별한다.
    - 영문 티커 (AAPL, NVDA 등)이면서
    - 국내 ETF가 아닌 경우
    """
    if not ticker:
        return False
    
    # 티커에서 거래소 접두사 제거 (NAS:NVDA -> NVDA)
    clean_ticker = ticker.split(":")[-1] if ":" in ticker else ticker
    
    # 숫자 포함 티커는 국내 종목 (005930 등)
    if any(c.isdigit() for c in clean_ticker):
        return False
    
    # 순수 영문 티커인지 확인
    if not clean_ticker.isalpha():
        return False
    
    # 국내 ETF 브랜드 키워드 체크
    domestic_etf_brands = ["KODEX", "TIGER", "ACE", "RISE", "SOL", "HANARO", "KBSTAR", "PLUS"]
    query_upper = query.upper() if query else ""
    if any(brand in query_upper for brand in domestic_etf_brands):
        return False
    
    # 2글자 이상의 영문 티커는 해외 종목으로 간주
    return len(clean_ticker) >= 2

async def search_news_logic(
    db: Session,
    query: str,
    ticker: Optional[str] = None,
    category: Optional[str] = None
) -> Dict:
    """
    관련 뉴스를 검색하고 실시간 수집을 수행하는 핵심 비즈니스 로직.
    """
    cleaned_query = clean_asset_name(query)
    market_keywords = extract_market_keywords(query)
    
    # 카테고리 추론
    is_economy = category == "economy" or ticker is not None or len(market_keywords) > 0
    
    # 티커 전처리
    clean_ticker = ticker
    if ticker and ":" in ticker:
        clean_ticker = ticker.split(":")[-1]
    
    # 실시간 검색어 후보군 생성
    realtime_search_terms = []
    if market_keywords:
        realtime_search_terms.append(market_keywords[0])
    
    if clean_ticker and clean_ticker.isalpha():
        if cleaned_query:
            realtime_search_terms.append(cleaned_query)
            realtime_search_terms.append(f"{cleaned_query} 주가")
            realtime_search_terms.append(f"{cleaned_query} {clean_ticker}")
        else:
            realtime_search_terms.append(clean_ticker)
    else:
        combined_term = f"{cleaned_query} {clean_ticker}" if clean_ticker else cleaned_query
        realtime_search_terms.append(combined_term)
    
    is_foreign = is_foreign_stock(ticker, query)
    
    # 1. 실시간 수집 수행
    try:
        collect_cat = "economy" if is_economy else "esports"
        if is_foreign:
            logger.info(f"Using Google News for foreign stock: ticker='{clean_ticker}', query='{cleaned_query}'")
            await collect_stock_news_google(db, clean_ticker, cleaned_query)
        else:
            for term in list(dict.fromkeys(realtime_search_terms))[:3]:
                logger.info(f"Triggering real-time collect for '{term}' (cat: {collect_cat})")
                await collect_naver_news(db, term, category=collect_cat)
    except Exception as e:
        logger.error(f"Error during real-time news collection: {e}")

    # 2. DB 검색
    filters = []
    search_tickers = [t for t in [clean_ticker, ticker] if t]
    for t in search_tickers:
        filters.append(GameNews.title.ilike(f"%{t}%"))
        filters.append(GameNews.full_content.ilike(f"%{t}%"))
        filters.append(GameNews.title.ilike(f"({t})"))
    
    for kw in market_keywords:
        filters.append(GameNews.title.ilike(f"%{kw}%"))
        
    if cleaned_query.upper() in ["LCK", "LPL", "LEC", "LCS", "VCT", "MSI", "WORLDS"]:
        filters.append(GameNews.league_tag == cleaned_query.upper())

    if cleaned_query and len(cleaned_query) >= 2:
        filters.append(GameNews.title.ilike(f"%{cleaned_query}%"))
        filters.append(GameNews.full_content.ilike(f"%{cleaned_query}%"))
        
    if not filters:
        articles = []
    else:
        query_obj = db.query(GameNews).filter(or_(*filters))
        if is_economy:
            query_obj = query_obj.filter(GameNews.source_name != "Steam")
            query_obj = query_obj.filter(GameNews.game_tag == "Economy")
            
        articles = query_obj.order_by(
            GameNews.event_time.desc().nulls_last(),
            GameNews.published_at.desc(), 
            GameNews.created_at.desc()
        ).limit(30).all()

    # 3. 노이즈 필터링
    ticker_volume_pattern = re.compile(f"{ticker}\\s*(주|건|매|원|달러|%|\\+|-)") if ticker and ticker.isdigit() else None
    product_noise_pattern = re.compile(r"(보수\s*전쟁|보수\s*인하|순자산\s*돌파|운용보수|총보수|배당금\s*지급|일정\s*변경|일반사무관리)")
    foreign_lang_pattern = re.compile(r"^[A-Za-zÀ-ÿ\s,.'\"!?¿¡-]+$")
    unrelated_industry_pattern = re.compile(r"(Lunsumio|룬수미오|피하주사|경쟁서|로슈|Roche|Eli Lilly|FDA)", re.IGNORECASE)
    
    filtered_articles = []
    for art in articles:
        if ticker_volume_pattern and (ticker_volume_pattern.search(art.title) or ticker_volume_pattern.search(art.full_content)):
            continue
        if market_keywords and product_noise_pattern.search(art.title):
            continue
        has_summary = hasattr(art, 'summary') and art.summary
        if not has_summary and foreign_lang_pattern.match(art.title.strip()):
            continue
        if unrelated_industry_pattern.search(art.title) or unrelated_industry_pattern.search(art.full_content or ""):
            continue
        filtered_articles.append(art)
    
    articles = filtered_articles[:15]
    
    result = []
    for art in articles:
        result.append({
            "id": art.id,
            "title": art.title,
            "url": art.url,
            "source_name": art.source_name,
            "published_at": art.published_at.isoformat() if art.published_at else None,
            "snippet": art.full_content[:150] + "..." if art.full_content and len(art.full_content) > 150 else (art.full_content or ""),
            "summary": art.summary if hasattr(art, 'summary') else None
        })
        
    return {
        "query": query,
        "ticker": ticker,
        "category": category,
        "count": len(result),
        "articles": result
    }
