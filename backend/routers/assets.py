from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import Asset, Trade
from ..schemas import AssetCalibration, AssetCreate, AssetRead, AssetUpdate, TradeCreate, TradeRead
from ..services.asset_service import calibrate_asset_balance
from ..services.portfolio import to_asset_read, to_trade_read
from ..services.trade_service import create_trade_with_sync
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.post("/assets", response_model=AssetRead)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)) -> AssetRead:
    user = get_or_create_single_user(db)
    
    # Validate: if amount > 0, at least one price must be provided
    if payload.amount > 0 and payload.purchase_price is None and payload.current_price is None:
        raise HTTPException(
            status_code=400, 
            detail="purchase_price or current_price required when amount > 0"
        )
    
    asset = Asset(
        user_id=user.id,
        name=payload.name,
        ticker=payload.ticker,
        category=payload.category,
        currency=payload.currency,
        amount=payload.amount,
        current_price=payload.current_price,
        purchase_price=payload.purchase_price,
        realized_profit=payload.realized_profit,
        index_group=payload.index_group,
        cma_config=payload.cma_config.model_dump() if payload.cma_config is not None else None,
    )
    db.add(asset)
    db.flush()  # Ensure asset.id is assigned

    if payload.amount > 0:
        # Create a matching BUY trade for initial balance
        trade_price = (
            payload.purchase_price
            if payload.purchase_price is not None
            else payload.current_price
        )
        trade = Trade(
            user_id=user.id,
            asset_id=asset.id,
            type="BUY",
            quantity=payload.amount,
            price=trade_price,
            timestamp=datetime.utcnow(),
            note="초기 자산 등록",
        )
        db.add(trade)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(asset)
    return to_asset_read(asset)


@router.patch("/assets/{asset_id}", response_model=AssetRead)
def update_asset(asset_id: int, payload: AssetUpdate, db: Session = Depends(get_db)) -> AssetRead:
    user = get_or_create_single_user(db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(asset, field, value)
    asset.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(asset)

    return to_asset_read(asset)


@router.post("/assets/{asset_id}/calibrate", response_model=AssetRead)
def calibrate_asset(
    asset_id: int,
    payload: AssetCalibration,
    db: Session = Depends(get_db),
) -> AssetRead:
    user = get_or_create_single_user(db)
    asset = calibrate_asset_balance(
        db,
        user.id,
        asset_id,
        payload.actual_amount,
        payload.actual_avg_price,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(asset)
    return to_asset_read(asset)


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)) -> dict:
    user = get_or_create_single_user(db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    # 소프트 삭제 - perform inside transaction
    asset.deleted_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"status": "ok"}


@router.post("/assets/{asset_id}/trades", response_model=TradeRead)
def create_trade_for_asset(
    asset_id: int,
    payload: TradeCreate,
    db: Session = Depends(get_db),
) -> TradeRead:
    user = get_or_create_single_user(db)
    item = payload.model_copy(update={"asset_id": asset_id})
    trade = create_trade_with_sync(db, user.id, item, sync_asset=True)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(trade)
    return to_trade_read(trade)
