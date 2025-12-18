from __future__ import annotations

from typing import Dict, List
import asyncio
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, RootModel
from sqlalchemy.orm import Session

from . import kis_client
from .auth import verify_api_token
from .db import get_db
from .models import Asset
from .routers.portfolio import router as portfolio_router, _get_or_create_single_user

app = FastAPI(title="MyAsset Portfolio Backend")


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


app.add_middleware(
    CORSMiddleware,
    # Backend는 Tailscale 등 사설 망 뒤에 두는 것을 전제로 하고,
    # 프론트는 Vercel 등 다양한 도메인에서 올 수 있으므로 일단 전체 허용.
    # 필요하면 추후 특정 도메인만 허용하도록 조정 가능.
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(portfolio_router)


@app.post(
    "/api/kis/prices",
    response_model=PricesResponse,
    dependencies=[Depends(verify_api_token)],
)
async def get_kis_prices(
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
    raw_tickers = [t.strip() for t in req.tickers if t and t.strip()]
    if not raw_tickers:
        raise HTTPException(status_code=400, detail="tickers list is empty")

    try:
        prices = await asyncio.to_thread(kis_client.fetch_kis_prices_krw, raw_tickers)
    except RuntimeError as exc:
        # KIS 인증/환경 설정 문제 등
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"KIS price fetch failed: {exc}",
        ) from exc

    if not prices:
        raise HTTPException(
            status_code=502,
            detail="no prices found for given tickers via KIS",
        )

    # --- 가격을 포트폴리오 자산에도 반영 ---
    try:
        user = _get_or_create_single_user(db)
        tickers = list(prices.keys())
        if tickers:
            assets = (
                db.query(Asset)
                .filter(
                    Asset.user_id == user.id,
                    Asset.deleted_at.is_(None),
                    Asset.ticker.in_(tickers),
                )
                .all()
            )

            now = datetime.utcnow()
            for asset in assets:
                if asset.ticker and asset.ticker in prices:
                    asset.current_price = prices[asset.ticker]
                    asset.updated_at = now

            if assets:
                db.commit()
    except Exception as exc:  # 저장 실패해도 시세 조회 응답은 유지
        # 로그만 남기고 조용히 무시
        # (개인용 프로젝트이므로 간단히 처리)
        print(f"[WARN] failed to persist synced prices: {exc}")

    return PricesResponse(root=prices)


@app.get("/api/search_ticker", response_model=TickerSearchResponse, dependencies=[Depends(verify_api_token)])
async def search_ticker(q: str = Query(..., min_length=1)) -> TickerSearchResponse:
    """
    종목명으로 검색 후,
    포트폴리오에서 사용할 KIS 호환 티커 포맷을 반환한다.

    - 국내: 6자리 숫자 코드 (예: 005930)
    - 미국: EXCD:SYMB 형식 (예: NAS:AAPL, NYS:VOO)
    - 데이터 출처: KIS 종목 마스터 엑셀 파일
    """
    try:
        raw_items = await asyncio.to_thread(kis_client.search_tickers_by_name, q)
    except RuntimeError as exc:
        # 마스터 파일이 없는 경우 등
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"KIS ticker search failed: {exc}",
        ) from exc

    results: List[TickerInfo] = []
    for item in raw_items:
        symbol = item.get("symbol") or ""
        name = item.get("name") or symbol
        exchange_label = item.get("exchange")
        currency = item.get("currency")
        quote_type = item.get("type")

        results.append(
            TickerInfo(
                symbol=symbol,
                name=name,
                exchange=exchange_label,
                currency=currency,
                type=quote_type,
            )
        )

    return TickerSearchResponse(query=q, results=results)


@app.get(
    "/api/kis/fx/usdkrw",
    response_model=FxRateResponse,
    dependencies=[Depends(verify_api_token)],
)
async def get_usdkrw_fx_rate() -> FxRateResponse:
    """
    한국투자증권 해외 현재가 상세 API를 사용해 USD/KRW 당일 환율을 조회한다.

    - 구현 단순화를 위해 미국 나스닥 상장 AAPL의 t_rate(당일환율)을 사용.
    - 참고용 환율이며, 실제 환전/과세 기준 환율과는 다를 수 있다.
    """
    try:
        rate = await asyncio.to_thread(kis_client.fetch_usdkrw_rate)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"KIS FX fetch failed: {exc}",
        ) from exc

    if rate is None:
        raise HTTPException(
            status_code=502,
            detail="no FX rate found from KIS",
        )

    return FxRateResponse(base="USD", quote="KRW", rate=rate)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    """브라우저에서 확인하기 위한 간단한 루트 페이지."""
    return """
    <!doctype html>
    <html lang="ko">
      <head>
        <meta charset="utf-8" />
        <title>MyAsset Portfolio Backend</title>
      </head>
      <body style="font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 24px;">
        <h1>MyAsset Portfolio Backend</h1>
        <p>✅ 서버가 정상적으로 실행 중입니다.</p>
        <ul>
          <li><code>GET /health</code> – 상태 확인 (JSON)</li>
          <li><code>POST /api/kis/prices</code> – 한국투자증권 Open API 기준 국내/해외 시세 조회 (KRW)</li>
          <li><code>GET /api/search_ticker</code> – 종목명으로 티커 검색</li>
        </ul>
      </body>
    </html>
    """
