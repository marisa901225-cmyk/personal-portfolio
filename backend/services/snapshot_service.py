from __future__ import annotations
from datetime import timedelta
from typing import List
from sqlalchemy.orm import Session

from ..core.models import PortfolioSnapshot
from ..core.time_utils import utcnow
from .portfolio import PortfolioService

def create_snapshot(db: Session, user_id: int) -> PortfolioSnapshot:
    """현재 포트폴리오 상태를 스냅샷으로 저장합니다."""
    return PortfolioService.create_snapshot(db, user_id)

def get_snapshots_recent(
    db: Session,
    user_id: int,
    days: int = 180
) -> List[PortfolioSnapshot]:
    """최근 N일 동안의 스냅샷 목록을 조회합니다."""
    since = utcnow() - timedelta(days=days)
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.user_id == user_id,
            PortfolioSnapshot.snapshot_at >= since,
        )
        .order_by(PortfolioSnapshot.snapshot_at.asc())
        .all()
    )
