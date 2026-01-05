from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import AiReport, User

router = APIRouter(prefix="/api", tags=["report"], dependencies=[Depends(verify_api_token)])


@router.get("/report/saved")
def get_saved_reports(
    db: Session = Depends(get_db),
) -> list[dict]:
    """저장된 AI 리포트 목록 조회 (최신순)"""
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        return []

    reports = (
        db.query(AiReport)
        .filter(AiReport.user_id == user.id)
        .order_by(AiReport.generated_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "period_year": r.period_year,
            "period_month": r.period_month,
            "period_quarter": r.period_quarter,
            "period_half": r.period_half,
            "query": r.query,
            "report": r.report,
            "model": r.model,
            "generated_at": r.generated_at.isoformat(),
            "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


@router.post("/report/saved")
def save_report(
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    """AI 리포트 저장"""
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=400, detail="사용자가 없습니다.")

    generated_at_str = payload.get("generated_at")
    if generated_at_str:
        try:
            generated_at = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
        except ValueError:
            generated_at = datetime.utcnow()
    else:
        generated_at = datetime.utcnow()

    report = AiReport(
        user_id=user.id,
        period_year=payload.get("period_year", datetime.utcnow().year),
        period_month=payload.get("period_month"),
        period_quarter=payload.get("period_quarter"),
        period_half=payload.get("period_half"),
        query=payload.get("query", ""),
        report=payload.get("report", ""),
        model=payload.get("model"),
        generated_at=generated_at,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {
        "id": report.id,
        "period_year": report.period_year,
        "period_month": report.period_month,
        "period_quarter": report.period_quarter,
        "period_half": report.period_half,
        "query": report.query,
        "report": report.report,
        "model": report.model,
        "generated_at": report.generated_at.isoformat(),
        "created_at": report.created_at.isoformat(),
    }


@router.delete("/report/saved/{report_id}")
def delete_saved_report(
    report_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """저장된 AI 리포트 삭제"""
    user = db.query(User).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=400, detail="사용자가 없습니다.")

    report = (
        db.query(AiReport)
        .filter(AiReport.id == report_id, AiReport.user_id == user.id)
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")

    db.delete(report)
    db.commit()

    return {"message": "삭제되었습니다.", "id": report_id}
