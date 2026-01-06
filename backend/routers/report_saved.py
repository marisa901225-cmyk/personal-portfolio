"""
Report Saved Router

저장된 AI 리포트 CRUD 엔드포인트.
비즈니스 로직은 report_service에서 처리하고, 라우터는 요청/응답 매핑만 담당한다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..services.report_service import (
    list_saved_reports,
    save_report,
    delete_saved_report,
)

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(verify_api_token)])


@router.get("/report/saved")
def get_saved_reports(
    db: Session = Depends(get_db),
) -> list[dict]:
    """저장된 AI 리포트 목록 조회 (최신순)"""
    return list_saved_reports(db)


@router.post("/report/saved")
def create_saved_report(
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    """AI 리포트 저장"""
    try:
        return save_report(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/report/saved/{report_id}")
def delete_report(
    report_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """저장된 AI 리포트 삭제"""
    try:
        return delete_saved_report(db, report_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
