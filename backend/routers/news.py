from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from ..core.db import get_db
from ..core.auth import verify_api_token
from ..core.rate_limit import rate_limit
from ..services import news_service

router = APIRouter(
    prefix="/api/news",
    tags=["News"],
    dependencies=[
        Depends(verify_api_token),
        Depends(rate_limit(limit=30, window_sec=60, key_prefix="news")),
    ],
)

@router.get("/search")
async def search_news(
    query: str = Query(..., description="검색어 (종목명, 게임명 등)"),
    ticker: Optional[str] = Query(None, description="티커 또는 종목코드"),
    category: Optional[str] = Query(None, description="카테고리 (economy, esports 등)"),
    db: Session = Depends(get_db)
):
    """
    관련 뉴스를 검색한다. 실시간 수집을 먼저 수행하여 최신성을 확보한다.
    비즈니스 로직은 news_service에서 처리한다.
    """
    return await news_service.search_news_logic(
        db=db,
        query=query,
        ticker=ticker,
        category=category
    )
