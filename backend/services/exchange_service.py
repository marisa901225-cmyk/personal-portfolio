from __future__ import annotations
from datetime import date
from typing import List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..core.models import FxTransaction
from ..core.schemas import FxTransactionCreate, FxTransactionUpdate
from ..core.time_utils import utcnow

def get_fx_transactions(
    db: Session,
    user_id: int,
    limit: int = 200,
    before_id: Optional[int] = None,
    kind: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[FxTransaction]:
    query = db.query(FxTransaction).filter(FxTransaction.user_id == user_id)

    if kind is not None:
        if kind not in {"BUY", "SELL", "SETTLEMENT"}:
            raise HTTPException(status_code=400, detail="invalid fx type")
        query = query.filter(FxTransaction.type == kind)

    if start_date is not None:
        query = query.filter(FxTransaction.trade_date >= start_date)
    if end_date is not None:
        query = query.filter(FxTransaction.trade_date <= end_date)

    if before_id is not None:
        query = query.filter(FxTransaction.id < before_id)

    return (
        query.order_by(FxTransaction.trade_date.desc(), FxTransaction.id.desc())
        .limit(limit)
        .all()
    )

def create_fx_transaction(
    db: Session,
    user_id: int,
    payload: FxTransactionCreate,
) -> FxTransaction:
    record = FxTransaction(
        user_id=user_id,
        trade_date=payload.trade_date,
        type=payload.type,
        currency=payload.currency,
        fx_amount=payload.fx_amount,
        krw_amount=payload.krw_amount,
        rate=payload.rate,
        description=payload.description,
        note=payload.note,
    )
    db.add(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(record)
    return record

def update_fx_transaction(
    db: Session,
    user_id: int,
    record_id: int,
    payload: FxTransactionUpdate,
) -> FxTransaction:
    record = (
        db.query(FxTransaction)
        .filter(FxTransaction.id == record_id, FxTransaction.user_id == user_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="fx transaction not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(record, field, value)
    record.updated_at = utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(record)
    return record

def delete_fx_transaction(
    db: Session,
    user_id: int,
    record_id: int,
) -> bool:
    record = (
        db.query(FxTransaction)
        .filter(FxTransaction.id == record_id, FxTransaction.user_id == user_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="fx transaction not found")

    db.delete(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True
