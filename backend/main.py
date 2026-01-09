"""
MyAsset Portfolio Backend - Main Application Entry Point

이 파일의 책임:
- FastAPI 앱 생성
- 미들웨어 설정
- 라우터 등록
- 헬스체크 및 루트 페이지

비즈니스 로직은 services/에, API 엔드포인트는 routers/에 위치한다.
"""

from __future__ import annotations

from typing import Dict
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from .core.db_migrations import ensure_schema
from .core import auth, db
from .routers.assets import router as assets_router
from .routers.exchanges import router as exchanges_router
from .routers.portfolio import router as portfolio_router
from .routers.report import router as report_router
from .routers.settings import router as settings_router
from .routers.snapshots import router as snapshots_router
from .routers.trades import router as trades_router
from .routers.cashflows import router as cashflows_router
from .routers.expenses import router as expenses_router
from .routers.expense_upload import router as expense_upload_router
from .routers.market_data import router as market_data_router
from .routers.spam_rules import router as spam_rules_router
from .routers.telegram_webhook import router as telegram_webhook_router

app = FastAPI(title="MyAsset Portfolio Backend")
ensure_schema()
logger = logging.getLogger("myasset.startup")


# ============================================
# Middleware
# ============================================

@app.middleware("http")
async def api_prefix_fallback(request: Request, call_next):
    """
    Reverse proxy(Tailscale Serve) 설정에 따라 /api prefix가 upstream에서 제거될 수 있다.
    이 경우에도 프론트가 사용하는 /api/* 라우팅을 그대로 지원하기 위해,
    /api 로 시작하지 않는 요청을 내부적으로 /api/* 로 매핑한다.
    """
    path = request.scope.get("path") or ""
    if (
        path
        and path not in ("/", "/health", "/openapi.json")
        and not path.startswith(("/api", "/docs", "/redoc"))
    ):
        request.scope["path"] = f"/api{path}"
    return await call_next(request)


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


# ============================================
# Startup Log
# ============================================

@app.on_event("startup")
def log_startup_info() -> None:
    logger.info("MyAsset Backend 시작")
    logger.info("DB 확인: %s", db.DATABASE_URL)
    logger.info("인증 모드: %s", "활성화" if auth.API_TOKEN else "비활성화")
    logger.info("Working Dir: %s", os.getcwd())


# ============================================
# Router Registration
# ============================================

app.include_router(portfolio_router)
app.include_router(report_router)
app.include_router(assets_router)
app.include_router(trades_router)
app.include_router(exchanges_router)
app.include_router(settings_router)
app.include_router(snapshots_router)
app.include_router(cashflows_router)
app.include_router(expenses_router)
app.include_router(expense_upload_router)
app.include_router(market_data_router)
app.include_router(spam_rules_router)
app.include_router(telegram_webhook_router)


# ============================================
# Health & Root
# ============================================

@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/health")
async def api_health() -> Dict[str, str]:
    return await health()


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
