from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ...core.models import AiReport
from ...core.time_utils import utcnow
from .core import get_user


def list_saved_reports(db: Session) -> list[dict]:
    """저장된 AI 리포트 목록을 조회한다."""
    user = get_user(db)
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


def save_report(db: Session, payload: dict) -> dict:
    """
    AI 리포트를 저장한다.

    Raises:
        ValueError: 사용자가 없는 경우
    """
    user = get_user(db)
    if not user:
        raise ValueError("사용자가 없습니다.")

    generated_at_str = payload.get("generated_at")
    if generated_at_str:
        try:
            generated_at = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
        except ValueError:
            generated_at = utcnow()
    else:
        generated_at = utcnow()

    report = AiReport(
        user_id=user.id,
        period_year=payload.get("period_year", utcnow().year),
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


def delete_saved_report(db: Session, report_id: int) -> dict:
    """
    저장된 AI 리포트를 삭제한다.

    Raises:
        ValueError: 사용자가 없는 경우
        LookupError: 리포트를 찾을 수 없는 경우
    """
    user = get_user(db)
    if not user:
        raise ValueError("사용자가 없습니다.")

    report = (
        db.query(AiReport)
        .filter(AiReport.id == report_id, AiReport.user_id == user.id)
        .first()
    )
    if not report:
        raise LookupError("리포트를 찾을 수 없습니다.")

    db.delete(report)
    db.commit()

    return {"message": "삭제되었습니다.", "id": report_id}
