from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..core.models import Trade, Asset
from ..core.schemas import TradeCreate
from ..core.time_utils import utcnow
from .crud_helpers import commit_or_rollback, commit_with_refresh, get_owned_row_or_404

ZERO_TOLERANCE = 1e-9


def create_trade_with_sync(
    db: Session, 
    user_id: int, 
    item: TradeCreate, 
    sync_asset: bool = True
) -> Trade:
    """
    거래 내역을 생성하고, sync_asset=True일 경우 자산(Asset)의 상태(잔고/평단)를 동기화합니다.
    
    NOTE: This function does NOT commit. The caller (router) is responsible for commit/rollback.
    """
    if item.quantity <= 0 or item.price <= 0:
        raise HTTPException(status_code=400, detail="quantity and price must be positive")
    if item.type not in {"BUY", "SELL"}:
        raise HTTPException(status_code=400, detail="invalid trade type")

    now = utcnow()
    timestamp = item.timestamp or now

    # 1. 자산 조회 with row lock
    asset = (
        db.query(Asset)
        .filter(
            Asset.id == item.asset_id,
            Asset.user_id == user_id,
            Asset.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    # 2. 거래 기록 생성 (History)
    realized_delta = None
    if sync_asset:
        realized_delta = _apply_trade_to_asset(asset, item.type, item.quantity, item.price, now)

    trade = Trade(
        user_id=user_id,
        asset_id=item.asset_id,
        type=item.type,
        quantity=item.quantity,
        price=item.price,
        timestamp=timestamp,
        realized_delta=realized_delta,
        note=item.note,
    )
    db.add(trade)
    db.flush()  # Ensure trade.id is assigned, but don't commit

    return trade


def _apply_trade_to_asset(asset: Asset, trade_type: str, quantity: float, price: float, now: datetime) -> float | None:
    """
    거래 타입에 따라 자산의 수량과 평단가를 갱신합니다 (이동평균법).
    """
    current_qty = asset.amount
    current_avg = asset.purchase_price or asset.current_price or price

    if trade_type == "BUY":
        new_qty = current_qty + quantity
        if new_qty <= 0:
            raise HTTPException(status_code=400, detail="invalid resulting amount")
        # 이동평균 단가 계산: (기존총액 + 매수총액) / 신규수량
        total_cost = (current_qty * current_avg) + (quantity * price)
        asset.purchase_price = total_cost / new_qty
        asset.amount = new_qty
        asset.current_price = price  # 최근 거래가로 현재가 갱신
        asset.updated_at = now
        asset.tags = "present"
        return None

    if trade_type == "SELL":
        if quantity > current_qty:
            raise HTTPException(status_code=400, detail="cannot sell more than current amount")

        # 매도 시 평단가는 변하지 않음 (수량만 감소)
        # 실현 손익 = (매도가 - 평단가) * 매도수량
        realized_delta = (price - current_avg) * quantity
        asset.realized_profit = (asset.realized_profit or 0.0) + realized_delta

        new_qty = current_qty - quantity
        asset.amount = new_qty
        asset.current_price = price
        asset.updated_at = now
        if new_qty < ZERO_TOLERANCE:
            asset.tags = "past"
            # asset.deleted_at = now  <-- 태그로 관리하므로 소프트 삭제 해제
        else:
            asset.tags = "present"
        return realized_delta

    raise HTTPException(status_code=400, detail="invalid trade type")

def get_trades(
    db: Session,
    user_id: int,
    limit: int = 100,
    before_id: int | None = None,
    asset_id: int | None = None,
) -> List[Trade]:
    query = db.query(Trade).filter(Trade.user_id == user_id)
    if asset_id is not None:
        query = query.filter(Trade.asset_id == asset_id)
    if before_id is not None:
        query = query.filter(Trade.id < before_id)
    return query.order_by(Trade.id.desc()).limit(limit).all()


def get_recent_trades(
    db: Session,
    user_id: int,
    limit: int = 20,
) -> List[Trade]:
    return (
        db.query(Trade)
        .filter(Trade.user_id == user_id)
        .order_by(Trade.timestamp.desc())
        .limit(limit)
        .all()
    )


def update_trade(
    db: Session,
    user_id: int,
    trade_id: int,
    data: dict,
) -> Trade:
    db_item = get_owned_row_or_404(db, Trade, trade_id, user_id, detail="Trade not found")
    for key, value in data.items():
        setattr(db_item, key, value)
    return commit_with_refresh(db, db_item)


def delete_trade(
    db: Session,
    user_id: int,
    trade_id: int,
) -> bool:
    db_item = get_owned_row_or_404(db, Trade, trade_id, user_id, detail="Trade not found")
    db.delete(db_item)
    commit_or_rollback(db)
    return True
