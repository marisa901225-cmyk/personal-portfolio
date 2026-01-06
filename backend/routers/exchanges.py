from __future__ import annotations

from datetime import date, datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import verify_api_token
from ..db import get_db
from ..models import FxTransaction
from ..schemas import FxTransactionCreate, FxTransactionRead, FxTransactionUpdate
from ..services.portfolio import to_fx_transaction_read
from ..services.users import get_or_create_single_user

router = APIRouter(prefix="/api", tags=["portfolio"], dependencies=[Depends(verify_api_token)])


@router.get("/exchanges", response_model=List[FxTransactionRead])
def get_fx_transactions(
    limit: int = Query(200, ge=1, le=500),
    before_id: int | None = Query(None, ge=1),
    kind: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: Session = Depends(get_db),
) -> List[FxTransactionRead]:
    user = get_or_create_single_user(db)
    query = db.query(FxTransaction).filter(FxTransaction.user_id == user.id)

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

    records = (
        query.order_by(FxTransaction.trade_date.desc(), FxTransaction.id.desc())
        .limit(limit)
        .all()
    )
    return [to_fx_transaction_read(r) for r in records]


@router.post("/exchanges", response_model=FxTransactionRead)
def create_fx_transaction(
    payload: FxTransactionCreate,
    db: Session = Depends(get_db),
) -> FxTransactionRead:
    user = get_or_create_single_user(db)
    record = FxTransaction(
        user_id=user.id,
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
    return to_fx_transaction_read(record)


@router.patch("/exchanges/{record_id}", response_model=FxTransactionRead)
def update_fx_transaction(
    record_id: int,
    payload: FxTransactionUpdate,
    db: Session = Depends(get_db),
) -> FxTransactionRead:
    user = get_or_create_single_user(db)
    record = (
        db.query(FxTransaction)
        .filter(FxTransaction.id == record_id, FxTransaction.user_id == user.id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="fx transaction not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(record, field, value)
    record.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(record)
    return to_fx_transaction_read(record)


@router.delete("/exchanges/{record_id}")
def delete_fx_transaction(
    record_id: int,
    db: Session = Depends(get_db),
) -> dict:
    user = get_or_create_single_user(db)
    record = (
        db.query(FxTransaction)
        .filter(FxTransaction.id == record_id, FxTransaction.user_id == user.id)
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
    return {"status": "ok"}
