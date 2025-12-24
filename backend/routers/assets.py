from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import Asset, Trade
from ..schemas import AssetCreate, AssetRead, AssetUpdate, TradeCreate, TradeRead
from ..services.portfolio import to_asset_read, to_trade_read
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.post("/assets", response_model=AssetRead)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)) -> AssetRead:
    user = get_or_create_single_user(db)
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
    # Ensure create is performed inside a transaction for atomicity
    with db.begin():
        db.add(asset)
        db.flush()
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

    # perform update inside transaction
    with db.begin():
        db.flush()
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
    with db.begin():
        db.flush()
    return {"status": "ok"}


@router.post("/assets/{asset_id}/trades", response_model=TradeRead)
def create_trade_for_asset(
    asset_id: int,
    payload: TradeCreate,
    db: Session = Depends(get_db),
) -> TradeRead:
    user = get_or_create_single_user(db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .with_for_update()
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    if payload.quantity <= 0 or payload.price <= 0:
        raise HTTPException(status_code=400, detail="quantity and price must be positive")

    now = datetime.utcnow()
    timestamp = payload.timestamp or now

    realized_delta = None

    if payload.type == "BUY":
        prev_amount = asset.amount
        prev_purchase_price = asset.purchase_price or asset.current_price or payload.price
        new_amount = prev_amount + payload.quantity
        if new_amount <= 0:
            raise HTTPException(status_code=400, detail="invalid resulting amount")
        new_purchase_price = (
            (prev_amount * prev_purchase_price + payload.quantity * payload.price) / new_amount
        )
        asset.amount = new_amount
        asset.purchase_price = new_purchase_price
        asset.current_price = payload.price
    elif payload.type == "SELL":
        if payload.quantity > asset.amount:
            raise HTTPException(
                status_code=400,
                detail="cannot sell more than current amount",
            )
        prev_amount = asset.amount
        avg_cost = asset.purchase_price or asset.current_price or payload.price
        new_amount = prev_amount - payload.quantity
        realized_delta = (payload.price - avg_cost) * payload.quantity
        asset.realized_profit = (asset.realized_profit or 0.0) + realized_delta
        asset.amount = new_amount
        asset.current_price = payload.price
        if new_amount <= 0:
            # 전량 매도 시 자산을 소프트 삭제 처리
            asset.deleted_at = now
    else:
        raise HTTPException(status_code=400, detail="invalid trade type")

    asset.updated_at = now

    trade = Trade(
        user_id=user.id,
        asset_id=asset.id,
        type=payload.type,
        quantity=payload.quantity,
        price=payload.price,
        timestamp=timestamp,
        realized_delta=realized_delta,
        note=payload.note,
    )

    # Ensure asset update and trade creation are atomic
    with db.begin():
        db.add(trade)
        db.flush()
        db.refresh(trade)

    return to_trade_read(trade)

