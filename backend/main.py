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
import os
import logging

from .core.logging_config import setup_global_logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from .core.db_migrations import ensure_schema
from .core import auth, db
from .services.alarm.llm_refiner import close_light_client
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
from .routers.news import router as news_router
from .routers.telegram_webhook import router as telegram_webhook_router
from .routers.memories import router as memories_router
from .routers.scheduler_state import router as scheduler_state_router


app = FastAPI(title="MyAsset Portfolio Backend")

# Logging Configuration (Sensitive Data Masking enabled)
setup_global_logging(logging.INFO)

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


app.add_middleware(GZipMiddleware, minimum_size=1000)


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
    logger.info("인증 모드: %s", "활성화" if auth.resolve_api_token() else "비활성화")
    logger.info("Working Dir: %s", os.getcwd())


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("MyAsset Backend 종료 중...")
    await close_light_client()


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
app.include_router(news_router)
app.include_router(telegram_webhook_router)
app.include_router(memories_router)
app.include_router(scheduler_state_router)



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
    """브라우저에서 확인하기 위한 루트 페이지."""
    return """
    <!doctype html>
    <html lang="ko">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>MyAsset API Service</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Pretendard:wght@400;600;800&display=swap" rel="stylesheet">
        <style>
          :root {
            --primary: #6366f1;
            --primary-dark: #4f46e5;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
            --text-light: #64748b;
          }
          body {
            font-family: 'Pretendard', system-ui, -apple-system, sans-serif;
            background-color: var(--bg);
            color: var(--text);
            line-height: 1.6;
            margin: 0;
            padding: 40px 20px;
            display: flex;
            justify-content: center;
          }
          .container {
            max-width: 800px;
            width: 100%;
          }
          header {
            margin-bottom: 40px;
            text-align: center;
          }
          h1 {
            font-size: 2.5rem;
            font-weight: 800;
            margin: 0;
            background: linear-gradient(135deg, var(--primary), #a855f7);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
          }
          .status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #f0fdf4;
            color: #166534;
            padding: 6px 12px;
            border-radius: 99px;
            font-size: 0.875rem;
            font-weight: 600;
            margin-top: 12px;
          }
          .status::before {
            content: '';
            width: 8px;
            height: 8px;
            background: #22c55e;
            border-radius: 50%;
            animation: pulse 2s infinite;
          }
          @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.7); }
            70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(34, 197, 94, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
          }
          .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 32px;
          }
          .card {
            background: var(--card-bg);
            padding: 24px;
            border-radius: 20px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            transition: transform 0.2s, box-shadow 0.2s;
          }
          .card:hover {
            transform: translateY(-4px);
            box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.1);
          }
          h2 {
            font-size: 1.25rem;
            margin: 0 0 12px 0;
            color: var(--primary);
            display: flex;
            align-items: center;
            gap: 8px;
          }
          ul {
            list-style: none;
            padding: 0;
            margin: 0;
          }
          li {
            padding: 8px 0;
            border-bottom: 1px solid #f1f5f9;
            font-size: 0.9rem;
          }
          li:last-child { border-bottom: none; }
          code {
            background: #f1f5f9;
            padding: 2px 6px;
            border-radius: 4px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.85em;
            color: #ef4444;
          }
          .docs-link {
            display: block;
            margin-top: 40px;
            text-align: center;
            text-decoration: none;
            background: var(--primary);
            color: white;
            padding: 14px 28px;
            border-radius: 12px;
            font-weight: 600;
            transition: background 0.2s;
          }
          .docs-link:hover {
            background: var(--primary-dark);
          }
        </style>
      </head>
      <body>
        <div class="container">
          <header>
            <h1>MyAsset Portfolio Backend</h1>
            <div class="status">시스템 정상 작동 중</div>
          </header>

          <div class="grid">
            <div class="card">
              <h2>📊 Portfolio & Assets</h2>
              <ul>
                <li><code>GET /api/portfolio</code> - 전체 포트폴리오 요약</li>
                <li><code>GET /api/assets</code> - 자산 목록 및 관리</li>
                <li><code>GET /api/trades</code> - 거래 내역 조회</li>
                <li><code>GET /api/snapshots</code> - 시계열 자산 스냅샷</li>
              </ul>
            </div>
            
            <div class="card">
              <h2>📰 News & Insights</h2>
              <ul>
                <li><code>GET /api/news/search</code> - 관련 뉴스 검색 (DuckDB)</li>
                <li><code>GET /api/report/ai</code> - AI 기반 포트폴리오 분석 리포트</li>
                <li><code>GET /api/market/prices</code> - 실시간 시세 조회 (KIS)</li>
              </ul>
            </div>

            <div class="card">
              <h2>💸 Expenses & Cashflows</h2>
              <ul>
                <li><code>GET /api/expenses</code> - 지출 내역 관리 및 분류</li>
                <li><code>POST /api/expenses/upload</code> - 지출 내역 엑셀 업로드</li>
                <li><code>GET /api/cashflows</code> - 연도별 입출금 현황</li>
              </ul>
            </div>

            <div class="card">
              <h2>⚙️ System</h2>
              <ul>
                <li><code>GET /health</code> - 서버 상태 체크</li>
                <li><code>GET /api/settings</code> - 시스템 설정 관리</li>
                <li><code>POST /api/spam_rules</code> - 알림 스팸 필터 규칙</li>
              </ul>
            </div>
          </div>

          <a href="/docs" class="docs-link">Swagger API 문서 보기</a>
        </div>
      </body>
    </html>
    """
