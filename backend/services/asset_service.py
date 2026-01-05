from __future__ import annotations
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import Asset

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
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # 변경 이력이나 로그를 남길 수도 있습니다.
    asset.amount = actual_amount
    asset.purchase_price = actual_avg_price
    
    # 잔고가 0이면 평단가도 의미가 없어지므로 처리 가능 (선택사항)
    if actual_amount == 0:
        asset.purchase_price = 0.0

    db.commit()
    db.refresh(asset)
    return asset
