from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import Trade
from ..schemas import TradeRead
from ..services.portfolio import to_trade_read
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.get("/trades", response_model=List[TradeRead])
def get_trades(
    limit: int = Query(100, ge=1, le=500),
    before_id: int | None = Query(None, ge=1),
    asset_id: int | None = Query(None, ge=1),
    db: Session = Depends(get_db),
) -> List[TradeRead]:
    """
    거래 내역을 최신순으로 페이지네이션해서 반환한다.

    - 기본 정렬: id desc (신규 거래가 항상 앞)
    - 다음 페이지: before_id 에 직전 페이지의 마지막 trade.id 를 넣어 조회
    """
    user = get_or_create_single_user(db)
    query = db.query(Trade).filter(Trade.user_id == user.id)

    if asset_id is not None:
        query = query.filter(Trade.asset_id == asset_id)

    if before_id is not None:
        query = query.filter(Trade.id < before_id)

    trades = query.order_by(Trade.id.desc()).limit(limit).all()
    return [to_trade_read(t) for t in trades]


@router.get("/trades/recent", response_model=List[TradeRead])
def get_recent_trades(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> List[TradeRead]:
    user = get_or_create_single_user(db)
    trades = (
        db.query(Trade)
        .filter(Trade.user_id == user.id)
        .order_by(Trade.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [to_trade_read(t) for t in trades]

