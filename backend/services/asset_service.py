from __future__ import annotations
from typing import List

from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..core.models import Asset, Trade
from ..core.schemas import AssetCreate, AssetUpdate, TradeBase, TradeCreate
from ..core.time_utils import utcnow
from ..services.users import get_or_create_single_user
from ..services.trade_service import create_trade_with_sync
from ..services.portfolio import to_asset_read, to_trade_read

ZERO_TOLERANCE = 1e-9


def get_assets(db: Session) -> List[dict]:
    """자산 목록 조회"""
    user = get_or_create_single_user(db)
    assets = db.query(Asset).filter(
        Asset.user_id == user.id, 
        Asset.deleted_at.is_(None)
    ).all()
    # Pydantic schema validation is better handled by caller or we return dicts
    # Retaining logic to return list of schemas dumped as dicts for consistency with standard service pattern
    return [to_asset_read(asset).model_dump() for asset in assets]


def create_asset(db: Session, payload: AssetCreate) -> dict:
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
        tags="present" if payload.amount > ZERO_TOLERANCE else "past",
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
            timestamp=utcnow(),
            note="초기 자산 등록",
        )
        db.add(trade)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(asset)
    return to_asset_read(asset).model_dump()


def update_asset(db: Session, asset_id: int, payload: AssetUpdate) -> dict:
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
    
    # Auto-update tags based on amount
    if abs(asset.amount) < ZERO_TOLERANCE:
        asset.tags = "past"
    elif asset.amount >= ZERO_TOLERANCE:
        asset.tags = "present"

    asset.updated_at = utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(asset)

    return to_asset_read(asset).model_dump()


def calibrate_asset_balance(
    db: Session, 
    user_id: int, 
    asset_id: int, 
    actual_amount: float, 
    actual_avg_price: float
) -> Asset:
    """
    [비상 탈출구] 거래 내역과 무관하게, 실제 증권사 앱의 잔고/평단가로 데이터를 덮어씁니다.
    """
    if actual_amount < 0:
        raise HTTPException(status_code=400, detail="actual_amount must be non-negative")
    if actual_avg_price < 0:
        raise HTTPException(status_code=400, detail="actual_avg_price must be non-negative")

    asset = (
        db.query(Asset)
        .filter(
            Asset.id == asset_id,
            Asset.user_id == user_id,
            Asset.deleted_at.is_(None),
        )
        .with_for_update()  # Row lock for concurrent access protection
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # 변경 이력이나 로그를 남길 수도 있습니다.
    asset.amount = actual_amount
    asset.purchase_price = actual_avg_price
    
    # 잔고가 0이면 평단가도 의미가 없어지므로 처리 가능 (선택사항)
    if abs(actual_amount) < ZERO_TOLERANCE:
        asset.purchase_price = 0.0
        asset.tags = "past"
    else:
        asset.tags = "present"
    
    # Caller is responsible for commit if not calling wrapper, 
    # but in this service method we are doing direct action, usually wrapped by calibrate_asset
    return asset


def calibrate_asset(
    db: Session,
    asset_id: int,
    actual_amount: float,
    actual_avg_price: float,
) -> dict:
    user = get_or_create_single_user(db)
    asset = calibrate_asset_balance(
        db,
        user.id,
        asset_id,
        actual_amount,
        actual_avg_price,
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(asset)
    return to_asset_read(asset).model_dump()


def delete_asset(db: Session, asset_id: int) -> dict:
    user = get_or_create_single_user(db)
    asset = (
        db.query(Asset)
        .filter(Asset.id == asset_id, Asset.user_id == user.id, Asset.deleted_at.is_(None))
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="asset not found")

    # 소프트 삭제 - perform inside transaction
    asset.deleted_at = utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"status": "ok"}


def create_trade_for_asset(
    db: Session,
    asset_id: int,
    payload: TradeBase,
) -> dict:
    user = get_or_create_single_user(db)
    item = TradeCreate(**payload.model_dump(), asset_id=asset_id)
    trade = create_trade_with_sync(db, user.id, item, sync_asset=True)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(trade)
    return to_trade_read(trade).model_dump()
