from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Dict, Optional
import logging
import re

from ..core.db import get_db
from ..core.models_misc import GameNews
from ..core.auth import verify_api_token
from ..services.news.naver import collect_naver_news
from ..services.news.google import collect_stock_news_google

router = APIRouter(prefix="/api/news", tags=["News"], dependencies=[Depends(verify_api_token)])
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

@router.get("/search")
async def search_news(
    query: str = Query(..., description="검색어 (종목명, 게임명 등)"),
    ticker: Optional[str] = Query(None, description="티커 또는 종목코드"),
    category: Optional[str] = Query(None, description="카테고리 (economy, esports 등)"),
    db: Session = Depends(get_db)
):
    """
    관련 뉴스를 검색한다. 실시간 수집을 먼저 수행하여 최신성을 확보한다.
    """
    cleaned_query = clean_asset_name(query)
    market_keywords = extract_market_keywords(query)
    
    # 카테고리 추론: 티커가 있거나 쿼리가 지수/경제 키워드를 포함하면 economy로 간주
    is_economy = category == "economy" or ticker is not None or len(market_keywords) > 0
    
    # 티커 전처리 (NAS:VELO -> VELO)
    clean_ticker = ticker
    if ticker and ":" in ticker:
        clean_ticker = ticker.split(":")[-1]
    
    # 실시간 검색어 후보군 생성 (Freshness 확보)
    realtime_search_terms = []
    
    # 1. 지수 관련 키워드
    if market_keywords:
        realtime_search_terms.append(market_keywords[0])
    
    # 2. 해외 주식/ETF 대응
    if clean_ticker and clean_ticker.isalpha():
        # 영문 티커인 경우:
        # - 티커 단독 검색은 노이즈가 많음 (VELO -> 제약 Lunsumio Velo 등)
        # - 종목명 + 티커 조합 또는 종목명 + "주가"로 검색
        if cleaned_query:
            # 1) "벨로3D" 또는 "Velo3D" 직접 검색 (가장 정확)
            realtime_search_terms.append(cleaned_query)
            # 2) "벨로3D 주가" (주가 키워드 조합)
            realtime_search_terms.append(f"{cleaned_query} 주가")
            # 3) "벨로3D VELO" (종목명 + 티커)
            realtime_search_terms.append(f"{cleaned_query} {clean_ticker}")
        else:
            # 종목명이 없으면 티커만 사용 (마지막 수단)
            realtime_search_terms.append(clean_ticker)
    else:
        # 국내 주식 등
        combined_term = f"{cleaned_query} {clean_ticker}" if clean_ticker else cleaned_query
        realtime_search_terms.append(combined_term)
    
    # 해외 종목 여부 판별
    is_foreign = is_foreign_stock(ticker, query)
    
    logger.info(f"Phase 6 Search: query='{query}', cleaned='{cleaned_query}', ticker='{ticker}', is_economy={is_economy}, is_foreign={is_foreign}")

    # 1. 실시간 수집 수행
    try:
        collect_cat = "economy" if is_economy else "esports"
        
        if is_foreign:
            # 해외 종목: 구글 뉴스 사용
            # - 영문 뉴스: LLM으로 한국어 요약
            # - 한국어 뉴스: 구글 한국어 RSS 사용
            logger.info(f"Using Google News for foreign stock: ticker='{clean_ticker}', query='{cleaned_query}'")
            await collect_stock_news_google(db, clean_ticker, cleaned_query)
        else:
            # 국내 종목: 네이버 뉴스 사용
            for term in list(dict.fromkeys(realtime_search_terms))[:3]:
                logger.info(f"Triggering real-time collect for '{term}' (cat: {collect_cat})")
                await collect_naver_news(db, term, category=collect_cat)
    except Exception as e:
        logger.error(f"Error during real-time news collection: {e}")

    def perform_search():
        filters = []
        # 티커 매칭 (전처리된 티커 및 원본 티커 모두 시도)
        search_tickers = [t for t in [clean_ticker, ticker] if t]
        for t in search_tickers:
            filters.append(GameNews.title.ilike(f"%{t}%"))
            filters.append(GameNews.full_content.ilike(f"%{t}%"))
            filters.append(GameNews.title.ilike(f"({t})"))
        
        # 지수 키워드 매칭 (가중치를 위해 상위에 배치)
        for kw in market_keywords:
            filters.append(GameNews.title.ilike(f"%{kw}%"))
            
        # e스포츠 리그 태그 매칭 (LCK 등)
        if cleaned_query.upper() in ["LCK", "LPL", "LEC", "LCS", "VCT", "MSI", "WORLDS"]:
            filters.append(GameNews.league_tag == cleaned_query.upper())

        # 정제된 이름 매칭
        if cleaned_query and len(cleaned_query) >= 2:
            filters.append(GameNews.title.ilike(f"%{cleaned_query}%"))
            filters.append(GameNews.full_content.ilike(f"%{cleaned_query}%"))
            
        if not filters:
            return []
            
        query_obj = db.query(GameNews).filter(or_(*filters))
        
        # Phase 6: 에셋 검색(Economy)인 경우 Steam 뉴스 제외 및 Economy 태그 우선
        if is_economy:
            query_obj = query_obj.filter(GameNews.source_name != "Steam")
            query_obj = query_obj.filter(GameNews.game_tag == "Economy")
            
        return query_obj.order_by(
            GameNews.event_time.desc().nulls_last(), # 일정 데이터는 이벤트 시간 우선
            GameNews.published_at.desc(), 
            GameNews.created_at.desc()
        ).limit(30).all()

    # 2. DB 검색 (신규 수집된 데이터 포함)
    articles = perform_search()
    
    # 3. 노이즈 필터링 (Phase 4 강화)
    ticker_volume_pattern = re.compile(f"{ticker}\\s*(주|건|매|원|달러|%|\\+|-)") if ticker and ticker.isdigit() else None
    product_noise_pattern = re.compile(r"(보수\s*전쟁|보수\s*인하|순자산\s*돌파|운용보수|총보수|배당금\s*지급|일정\s*변경|일반사무관리)")
    
    # 외국어 감지 패턴 (스페인어, 영어 전용 기사 등)
    foreign_lang_pattern = re.compile(r"^[A-Za-zÀ-ÿ\s,.'\"!?¿¡-]+$")  # 한글/한자 없는 기사
    
    # 관련 없는 산업 필터링 (티커가 다른 산업에서도 쓰이는 경우)
    # 예: VELO -> Lunsumio Velo (제약), 벨로(자전거 브랜드) 등
    unrelated_industry_pattern = re.compile(r"(Lunsumio|룬수미오|피하주사|경쟁서|로슈|Roche|Eli Lilly|FDA)", re.IGNORECASE)
    
    filtered_articles = []
    for art in articles:
        # 티커 거래량 노이즈
        if ticker_volume_pattern and (ticker_volume_pattern.search(art.title) or ticker_volume_pattern.search(art.full_content)):
            continue
            
        # 상품 홍보/관리성 노이즈 (지수 뉴스를 보고 싶은 경우)
        if market_keywords and product_noise_pattern.search(art.title):
            logger.info(f"Filtering out product noise: {art.title}")
            continue
        
        # 외국어 기사 필터링 (스페인어, 영어 전용 등)
        # 단, summary가 있는 경우는 의도적으로 수집한 해외 뉴스이므로 제외하지 않음
        has_summary = hasattr(art, 'summary') and art.summary
        if not has_summary and foreign_lang_pattern.match(art.title.strip()):
            logger.info(f"Filtering out foreign language article: {art.title[:50]}...")
            continue
        
        # 관련 없는 산업 필터링 (제약사 Lunsumio Velo 등)
        if unrelated_industry_pattern.search(art.title) or unrelated_industry_pattern.search(art.full_content or ""):
            logger.info(f"Filtering out unrelated industry article: {art.title[:50]}...")
            continue
            
        filtered_articles.append(art)
    
    articles = filtered_articles[:15] # 최종 15개 추천
    logger.info(f"Final search found {len(articles)} articles.")
        
    result = []
    for art in articles:
        result.append({
            "id": art.id,
            "title": art.title,
            "url": art.url,
            "source_name": art.source_name,
            "published_at": art.published_at.isoformat() if art.published_at else None,
            "snippet": art.full_content[:150] + "..." if art.full_content and len(art.full_content) > 150 else (art.full_content or ""),
            "summary": art.summary if hasattr(art, 'summary') else None  # 영문 뉴스의 한국어 요약
        })
        
    return {
        "query": query,
        "ticker": ticker,
        "category": category,
        "count": len(result),
        "articles": result
    }
