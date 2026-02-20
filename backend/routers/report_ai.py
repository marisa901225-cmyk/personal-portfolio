"""
Report AI Router

AI 리포트 생성 엔드포인트.
비즈니스 로직(입력해석, 집계, AI 호출, 스트리밍)은 report_service에서 처리하고,
라우터는 요청/응답 매핑(HTTPException 처리 등)만 담당한다.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.rate_limit import rate_limit
from ..core.schemas import ReportAiResponse, ReportAiTextResponse
from ..services.report_service import (
    resolve_ai_report_prompt,
    generate_ai_report_text,
    generate_ai_report_stream,
    get_ai_report_metrics,
    get_refined_report_data,
)

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(verify_api_token)])
logger = logging.getLogger(__name__)


@router.get("/report/ai", response_model=ReportAiResponse)
def get_report_ai_metrics(
    year: int = Query(..., ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    top_n: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
) -> ReportAiResponse:
    """AI 리포트 화면용 통계 데이터 및 Top 자산 집계."""
    if month is not None and quarter is not None:
        raise HTTPException(status_code=400, detail="use either month or quarter, not both")
    return get_ai_report_metrics(db, year, month, quarter, top_n)


@router.get("/report/ai/text", response_model=ReportAiTextResponse)
async def get_report_ai_text(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    query: str | None = Query(None),
    model: str | None = Query(None),
    max_tokens: int | None = Query(None, ge=256, le=10000),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit(limit=12, window_sec=60, key_prefix="ai_report")),
) -> ReportAiTextResponse:
    """AI 리포트 텍스트 생성 (Non-streaming)."""
    try:
        period, prompt = resolve_ai_report_prompt(db, year, month, quarter, query)
        return await generate_ai_report_text(period, prompt, model, max_tokens)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.exception("AI report generation failed")
        raise HTTPException(status_code=502, detail="AI report generation failed")


@router.get("/report/ai/text/stream")
def get_report_ai_text_stream(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
    query: str | None = Query(None),
    model: str | None = Query(None),
    max_tokens: int | None = Query(None, ge=256, le=10000),
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit(limit=12, window_sec=60, key_prefix="ai_report_stream")),
) -> StreamingResponse:
    """AI 리포트 텍스트 생성 (Streaming)."""
    try:
        period, prompt = resolve_ai_report_prompt(db, year, month, quarter, query)
        return StreamingResponse(
            generate_ai_report_stream(period, prompt, model, max_tokens),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("AI report stream initialization failed")
        raise HTTPException(status_code=500, detail="Streaming initialization failed")


@router.get("/report/refined")
def get_refined_report(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    quarter: int | None = Query(None, ge=1, le=4),
) -> dict:
    """DuckDB 기반의 정제된 데이터 반환 (호환성 유지용)."""
    try:
        return get_refined_report_data(year=year, month=month, quarter=quarter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DuckDB refinement failed: {exc}") from exc
