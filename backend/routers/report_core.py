"""
Report Core Router

기본 리포트 엔드포인트.
비즈니스 로직은 report_service에서 처리하고, 라우터는 요청/응답 매핑만 담당한다.
"""
from __future__ import annotations

from datetime import date
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
    build_report,
    build_monthly_summaries,
    aggregate_activity,
    get_user,
)

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(verify_api_token)])


@router.get("/report", response_model=ReportResponse)
def get_report(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
) -> ReportResponse:
    if month is not None and year is None:
        raise HTTPException(status_code=400, detail="year is required when month is set")

    start_date = None
    end_date = None
    if year is not None:
        if month is None:
            start_date = date(year, 1, 1)
            end_date = date(year + 1, 1, 1)
        else:
            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1)
            else:
                end_date = date(year, month + 1, 1)

    return build_report(db, start_date, end_date)


@router.get("/report/yearly", response_model=ReportResponse)
def get_report_yearly(
    year: int = Query(..., ge=1970),
    db: Session = Depends(get_db),
) -> ReportResponse:
    start_date = date(year, 1, 1)
    end_date = date(year + 1, 1, 1)
    return build_report(db, start_date, end_date)


@router.get("/report/monthly", response_model=ReportResponse)
def get_report_monthly(
    year: int = Query(..., ge=1970),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
) -> ReportResponse:
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
    return build_report(db, start_date, end_date)


@router.get("/report/quarterly", response_model=ReportResponse)
def get_report_quarterly(
    year: int = Query(..., ge=1970),
    quarter: int = Query(..., ge=1, le=4),
    db: Session = Depends(get_db),
) -> ReportResponse:
    start_month = (quarter - 1) * 3 + 1
    start_date = date(year, start_month, 1)
    if quarter == 4:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, start_month + 3, 1)
    return build_report(db, start_date, end_date)


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
    user = get_user(db)
    monthly = build_monthly_summaries(db, user, year)
    summaries = []
    for quarter in range(1, 5):
        start_month = (quarter - 1) * 3 + 1
        months = [start_month, start_month + 1, start_month + 2]
        activity = aggregate_activity(monthly, months)
        summaries.append(
            QuarterlyReportSummary(
                year=year,
                quarter=quarter,
                trade_count=activity.trade_count,
                trade_buy_value=activity.trade_buy_value,
                trade_sell_value=activity.trade_sell_value,
                cashflow_count=activity.cashflow_count,
                cashflow_total=activity.cashflow_total,
                fx_transaction_count=activity.fx_transaction_count,
                snapshot_count=activity.snapshot_count,
            )
        )

    return summaries
