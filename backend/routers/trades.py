from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import TradeRead, TradeCreate, TradeUpdate
from ..services import trade_service
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
    user = get_or_create_single_user(db)
    trades = trade_service.get_trades(db, user.id, limit, before_id, asset_id)
    return [to_trade_read(t) for t in trades]


@router.get("/trades/recent", response_model=List[TradeRead])
def get_recent_trades(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> List[TradeRead]:
    user = get_or_create_single_user(db)
    trades = trade_service.get_recent_trades(db, user.id, limit)
    return [to_trade_read(t) for t in trades]


@router.post("/trades", response_model=TradeRead)
def create_trade(item: TradeCreate, db: Session = Depends(get_db)):
    user = get_or_create_single_user(db)
    db_item = trade_service.create_trade_with_sync(db, user.id, item, sync_asset=True)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_item)
    return to_trade_read(db_item)


@router.put("/trades/{trade_id}", response_model=TradeRead)
def update_trade(trade_id: int, item: TradeUpdate, db: Session = Depends(get_db)):
    user = get_or_create_single_user(db)
    db_item = trade_service.update_trade(db, user.id, trade_id, item.model_dump(exclude_unset=True))
    return to_trade_read(db_item)


@router.delete("/trades/{trade_id}")
def delete_trade(trade_id: int, db: Session = Depends(get_db)):
    user = get_or_create_single_user(db)
    trade_service.delete_trade(db, user.id, trade_id)
    return {"message": "Trade deleted"}
