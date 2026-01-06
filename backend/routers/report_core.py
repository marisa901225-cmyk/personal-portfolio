"""
Report Core Router

기본 리포트 엔드포인트.
비즈니스 로직은 report_service에서 처리하고, 라우터는 요청/응답 매핑만 담당한다.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..schemas import (
    MonthlyReportSummary,
    QuarterlyReportSummary,
    ReportResponse,
)
from ..services.report_service import (
    get_report_data,
    build_monthly_summaries,
    get_quarterly_summaries,
    get_user,
)

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(verify_api_token)])


@router.get("/report", response_model=ReportResponse)
def get_report(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
) -> ReportResponse:
    """통합 리포트 데이터 조회 (연/월간 자동 처리)."""
    if month is not None and year is None:
        raise HTTPException(status_code=400, detail="year is required when month is set")
    return get_report_data(db, year=year, month=month)


@router.get("/report/yearly", response_model=ReportResponse)
def get_report_yearly(
    year: int = Query(..., ge=1970),
    db: Session = Depends(get_db),
) -> ReportResponse:
    return get_report_data(db, year=year)


@router.get("/report/monthly", response_model=ReportResponse)
def get_report_monthly(
    year: int = Query(..., ge=1970),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> ReportResponse:
    return get_report_data(db, year=year, month=month)


@router.get("/report/quarterly", response_model=ReportResponse)
def get_report_quarterly(
    year: int = Query(..., ge=1970),
    quarter: int = Query(..., ge=1, le=4),
    db: Session = Depends(get_db),
) -> ReportResponse:
    return get_report_data(db, year=year, quarter=quarter)


@router.get("/report/monthly/summary", response_model=List[MonthlyReportSummary])
def get_monthly_report_summary(
    year: int = Query(..., ge=1970),
    db: Session = Depends(get_db),
) -> List[MonthlyReportSummary]:
    user = get_user(db)
    summaries = build_monthly_summaries(db, user, year)
    return [summaries[month] for month in range(1, 13)]


@router.get("/report/quarterly/summary", response_model=List[QuarterlyReportSummary])
def get_quarterly_report_summary(
    year: int = Query(..., ge=1970),
    db: Session = Depends(get_db),
) -> List[QuarterlyReportSummary]:
    """분기 요약 집계 (집계 로직은 서비스에서 처리)."""
    return get_quarterly_summaries(db, year)
