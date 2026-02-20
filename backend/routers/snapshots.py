from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import PortfolioSnapshotRead
from ..services import snapshot_service
from ..services.portfolio import to_snapshot_read
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.post("/portfolio/snapshots", response_model=PortfolioSnapshotRead)
def create_portfolio_snapshot(db: Session = Depends(get_db)) -> PortfolioSnapshotRead:
    """현재 포트폴리오 상태(총자산/원금/손익 요약)를 스냅샷으로 저장한다."""
    user = get_or_create_single_user(db)
    snapshot = snapshot_service.create_snapshot(db, user.id)
    return to_snapshot_read(snapshot)


@router.get("/portfolio/snapshots", response_model=List[PortfolioSnapshotRead])
def get_portfolio_snapshots(
    days: int = Query(180, ge=1, le=3650),
    db: Session = Depends(get_db),
) -> List[PortfolioSnapshotRead]:
    """최근 N일 동안의 포트폴리오 스냅샷 목록을 반환한다."""
    user = get_or_create_single_user(db)
    snapshots = snapshot_service.get_snapshots_recent(db, user.id, days)
    return [to_snapshot_read(s) for s in snapshots]
