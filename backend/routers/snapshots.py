from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.models import Asset, ExternalCashflow, PortfolioSnapshot
from ..core.schemas import PortfolioSnapshotRead
from ..services.portfolio import calculate_summary, to_snapshot_read
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.post("/portfolio/snapshots", response_model=PortfolioSnapshotRead)
def create_portfolio_snapshot(db: Session = Depends(get_db)) -> PortfolioSnapshotRead:
    """
    현재 포트폴리오 상태(총자산/원금/손익 요약)를 스냅샷으로 저장한다.

    - 용도: cron/systemd timer 등에서 하루 1번 호출하여 히스토리 차트 데이터로 사용.
    """
    user = get_or_create_single_user(db)
    assets = (
        db.query(Asset)
        .filter(Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .all()
    )
    external_cashflows = (
        db.query(ExternalCashflow)
        .filter(ExternalCashflow.user_id == user.id)
        .all()
    )
    summary = calculate_summary(assets, external_cashflows)
    now = datetime.utcnow()

    snapshot = PortfolioSnapshot(
        user_id=user.id,
        snapshot_at=now,
        total_value=summary.total_value,
        total_invested=summary.total_invested,
        realized_profit_total=summary.realized_profit_total,
        unrealized_profit_total=summary.unrealized_profit_total,
    )
    db.add(snapshot)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(snapshot)

    return to_snapshot_read(snapshot)


@router.get("/portfolio/snapshots", response_model=List[PortfolioSnapshotRead])
def get_portfolio_snapshots(
    days: int = Query(180, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> List[PortfolioSnapshotRead]:
    """
    최근 N일 동안의 포트폴리오 스냅샷 목록을 반환한다.

    - 기본값: 180일 (약 6개월)
    - 프론트 히스토리 차트에서 사용.
    """
    user = get_or_create_single_user(db)
    since = datetime.utcnow() - timedelta(days=days)

    snapshots = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user.id,
            PortfolioSnapshot.snapshot_at >= since,
        )
        .order_by(PortfolioSnapshot.snapshot_at.asc())
        .all()
    )

    return [to_snapshot_read(s) for s in snapshots]
