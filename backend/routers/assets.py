from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import AssetCalibration, AssetCreate, AssetRead, AssetUpdate, TradeBase, TradeRead
from ..services import asset_service

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.get("/assets", response_model=list[AssetRead])
def get_assets(db: Session = Depends(get_db)) -> list[AssetRead]:
    """자산 목록 조회"""
    return asset_service.get_assets(db)


@router.post("/assets", response_model=AssetRead)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)) -> AssetRead:
    return asset_service.create_asset(db, payload)


@router.patch("/assets/{asset_id}", response_model=AssetRead)
def update_asset(asset_id: int, payload: AssetUpdate, db: Session = Depends(get_db)) -> AssetRead:
    return asset_service.update_asset(db, asset_id, payload)


@router.post("/assets/{asset_id}/calibrate", response_model=AssetRead)
def calibrate_asset(
    asset_id: int,
    payload: AssetCalibration,
    db: Session = Depends(get_db),
) -> AssetRead:
    return asset_service.calibrate_asset(
        db,
        asset_id,
        payload.actual_amount,
        payload.actual_avg_price,
    )


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)) -> dict:
    return asset_service.delete_asset(db, asset_id)


@router.post("/assets/{asset_id}/trades", response_model=TradeRead)
def create_trade_for_asset(
    asset_id: int,
    payload: TradeBase,
    db: Session = Depends(get_db),
) -> TradeRead:
    return asset_service.create_trade_for_asset(db, asset_id, payload)
