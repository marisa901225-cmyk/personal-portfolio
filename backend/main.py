from __future__ import annotations

from typing import Dict, List
import os

from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, RootModel

import httpx

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

API_TOKEN = os.getenv("API_TOKEN")


async def verify_api_token(x_api_token: str | None = Header(default=None)) -> None:
    """
    간단한 토큰 기반 인증.
    - 환경변수 API_TOKEN 이 설정되어 있지 않으면 인증을 강제하지 않는다.
    - 설정되어 있다면, 요청 헤더 X-API-Token 과 동일해야 통과.
    """
    if not API_TOKEN:
        return
    if not x_api_token or x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid api token")


@app.post("/api/prices", response_model=PricesResponse, dependencies=[Depends(verify_api_token)])
async def get_prices(req: PricesRequest) -> PricesResponse:
    """
    Yahoo Finance에서 현재가를 조회해 KRW 기준으로 반환한다.

    - 입력: tickers (예: 005930.KS, AAPL, VOO 등)
    - 처리:
        - https://query1.finance.yahoo.com/v7/finance/quote 로 일괄 조회
        - 각 티커의 regularMarketPrice 사용
        - currency가 USD인 경우:
            - USDKRW=X 시세를 추가로 조회하여 KRW로 환산
    - 출력: { "티커": 현재가(KRW) } 형태의 맵
    """
    raw_tickers = [t.strip() for t in req.tickers if t and t.strip()]
    if not raw_tickers:
        raise HTTPException(status_code=400, detail="tickers list is empty")

    # 중복 제거 및 정렬(디버깅 편의를 위해)
    symbols: List[str] = sorted(set(raw_tickers))

    quote_url = "https://query1.finance.yahoo.com/v7/finance/quote"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(quote_url, params={"symbols": ",".join(symbols)})
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"price fetch failed: {exc}") from exc

    data = resp.json()
    results = (data.get("quoteResponse") or {}).get("result") or []

    by_symbol: Dict[str, Dict] = {}
    for item in results:
        symbol = item.get("symbol")
        if not symbol:
            continue
        by_symbol[symbol] = item

    # USD 자산이 하나라도 있으면 USDKRW 환율을 조회
    needs_usdkrw = any(
        (by_symbol.get(sym) or {}).get("currency") == "USD"
        for sym in symbols
    )

    usdkrw_rate: float = 1.0
    if needs_usdkrw:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                fx_resp = await client.get(quote_url, params={"symbols": "USDKRW=X"})
            fx_resp.raise_for_status()
            fx_data = fx_resp.json()
            fx_results = (fx_data.get("quoteResponse") or {}).get("result") or []
            for item in fx_results:
                if item.get("symbol") == "USDKRW=X":
                    price = item.get("regularMarketPrice")
                    if price is not None:
                        usdkrw_rate = float(price)
                    break
        except httpx.HTTPError:
            # 환율 조회 실패 시에도 서비스 전체가 죽지 않도록 1.0으로 유지
            usdkrw_rate = 1.0

    prices: Dict[str, float] = {}
    for sym in symbols:
        info = by_symbol.get(sym)
        if not info:
            # Yahoo에서 찾지 못한 티커는 건너뛰고, 프론트에서는 기존 가격 유지
            continue

        price = info.get("regularMarketPrice")
        if price is None:
            continue

        currency = info.get("currency") or "KRW"
        value = float(price)

        # 기본 통화는 KRW 그대로 사용, USD는 환율 곱해서 KRW로 변환
        if currency == "USD" and usdkrw_rate > 0:
            value *= usdkrw_rate

        prices[sym] = value

    if not prices:
        raise HTTPException(status_code=502, detail="no prices found for given tickers")

    return PricesResponse(root=prices)


@app.get("/api/search_ticker", response_model=TickerSearchResponse, dependencies=[Depends(verify_api_token)])
async def search_ticker(q: str = Query(..., min_length=1)) -> TickerSearchResponse:
    """
    종목명으로 Yahoo Finance 검색 후,
    상위 몇 개 결과를 반환한다.
    """
    url = "https://query1.finance.yahoo.com/v1/finance/search"
    params = {"q": q, "quotesCount": 5, "newsCount": 0}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"price search failed: {exc}") from exc

    data = resp.json()
    quotes = data.get("quotes", []) or []

    results: List[TickerInfo] = []
    for item in quotes:
        symbol = item.get("symbol")
        if not symbol:
            continue
        name = (
            item.get("shortname")
            or item.get("longname")
            or symbol
        )
        results.append(
            TickerInfo(
                symbol=symbol,
                name=name,
                exchange=item.get("exchDisp"),
                currency=item.get("currency"),
                type=item.get("quoteType"),
            )
        )

    return TickerSearchResponse(query=q, results=results)


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
          <li><code>POST /api/prices</code> – 가격 조회</li>
          <li><code>GET /api/search_ticker</code> – 종목명으로 티커 검색</li>
        </ul>
      </body>
    </html>
    """
