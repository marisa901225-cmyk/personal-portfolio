"""
Market Data Router

KIS(한국투자증권) 관련 API 엔드포인트.

- POST /api/kis/prices - 시세 조회
- GET /api/search_ticker - 티커 검색
- GET /api/kis/fx/usdkrw - USD/KRW 환율 조회

라우터는 요청/응답 검증 및 HTTP 예외 매핑만 담당하고,
비즈니스 로직은 market_data_service에서 처리한다.
"""

from __future__ import annotations

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, RootModel
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.models import Setting
from ..services.market_data_service import (
    get_kis_prices_krw,
    search_tickers_by_name,
    get_usdkrw_rate,
    KisConfigurationError,
    KisApiError,
    EmptyResultError,
)
from ..services.users import get_or_create_single_user


router = APIRouter(tags=["Market Data"])


# ============================================
# Pydantic Models (기존 main.py에서 이동)
# ============================================

class PricesRequest(BaseModel):
    tickers: List[str]


class PricesResponse(RootModel[Dict[str, float]]):
    """단순 티커 → 가격 매핑을 감싸는 루트 모델 (Pydantic v2 스타일)."""
    pass


class TickerInfo(BaseModel):
    symbol: str
    name: str
    exchange: str | None = None
    currency: str | None = None
    type: str | None = None


class TickerSearchResponse(BaseModel):
    query: str
    results: List[TickerInfo]


class FxRateResponse(BaseModel):
    base: str
    quote: str
    rate: float


# ============================================
# Endpoints
# ============================================

@router.post(
    "/api/kis/prices",
    response_model=PricesResponse,
    dependencies=[Depends(verify_api_token)],
)
async def get_prices(
    req: PricesRequest,
    db: Session = Depends(get_db),
) -> PricesResponse:
    """
    한국투자증권 Open API 기준으로 국내/해외 시세를 조회한다.

    - 국내: 6자리 숫자 종목코드 (예: 005930)
    - 해외: EXCD:SYMB 형식 (예: NAS:AAPL, NYS:VOO)
      * EXCD: KIS 거래소 코드 (NAS, NYS, AMS, HKS, TSE 등)
    - 응답값은 모두 KRW 기준 가격으로 반환된다.
    """
    try:
        prices = await get_kis_prices_krw(req.tickers, db)
        return PricesResponse(root=prices)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KisConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (KisApiError, EmptyResultError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/api/search_ticker",
    response_model=TickerSearchResponse,
    dependencies=[Depends(verify_api_token)],
)
async def search_ticker(
    q: str = Query(..., min_length=1),
) -> TickerSearchResponse:
    """
    종목명으로 검색 후,
    포트폴리오에서 사용할 KIS 호환 티커 포맷을 반환한다.

    - 국내: 6자리 숫자 코드 (예: 005930)
    - 미국: EXCD:SYMB 형식 (예: NAS:AAPL, NYS:VOO)
    - 데이터 출처: KIS 종목 마스터 엑셀 파일
    """
    try:
        raw_items = await search_tickers_by_name(q)
    except KisConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except KisApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    results: List[TickerInfo] = [
        TickerInfo(
            symbol=item.get("symbol") or "",
            name=item.get("name") or item.get("symbol") or "",
            exchange=item.get("exchange"),
            currency=item.get("currency"),
            type=item.get("type"),
        )
        for item in raw_items
    ]

    return TickerSearchResponse(query=q, results=results)


@router.get(
    "/api/kis/fx/usdkrw",
    response_model=FxRateResponse,
    dependencies=[Depends(verify_api_token)],
)
async def get_fx_rate(
    db: Session = Depends(get_db),
    fresh: bool = Query(False, description="캐시 무시하고 KIS API에서 새로 조회"),
) -> FxRateResponse:
    """
    한국투자증권 해외 현재가 상세 API를 사용해 USD/KRW 당일 환율을 조회한다.

    - 기본: DB에 캐시된 환율 반환 (즉시 응답)
    - fresh=true: KIS API에서 새로 조회 후 캐시 갱신
    - 캐시가 없으면 자동으로 KIS API 호출
    - 참고용 환율이며, 실제 환전/과세 기준 환율과는 다를 수 있다.
    """
    from ..services.market_data_service import get_cached_fx_rate, update_cached_fx_rate
    
    # 캐시 우선 사용 (fresh=false일 때)
    if not fresh:
        cached = get_cached_fx_rate(db)
        if cached is not None:
            return FxRateResponse(base="USD", quote="KRW", rate=cached)
    
    # KIS API 호출
    try:
        rate = await get_usdkrw_rate()
        logger.info(f"Fetched fresh USD/KRW rate from KIS: {rate}")
        # 캐시 갱신
        update_cached_fx_rate(db, rate)
        return FxRateResponse(base="USD", quote="KRW", rate=rate)
    except KisConfigurationError as exc:
        cached = get_cached_fx_rate(db)
        if cached is not None:
            return FxRateResponse(base="USD", quote="KRW", rate=cached)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (KisApiError, EmptyResultError) as exc:
        # API 실패 시에도 캐시 반환 시도
        cached = get_cached_fx_rate(db)
        if cached is not None:
            return FxRateResponse(base="USD", quote="KRW", rate=cached)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
