from __future__ import annotations

from datetime import date
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import FxTransactionCreate, FxTransactionRead, FxTransactionUpdate
from ..services import exchange_service
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
    records = exchange_service.get_fx_transactions(
        db, user.id, limit, before_id, kind, start_date, end_date
    )
    return [to_fx_transaction_read(r) for r in records]


@router.post("/exchanges", response_model=FxTransactionRead)
def create_fx_transaction(
    payload: FxTransactionCreate,
    db: Session = Depends(get_db),
) -> FxTransactionRead:
    user = get_or_create_single_user(db)
    record = exchange_service.create_fx_transaction(db, user.id, payload)
    return to_fx_transaction_read(record)


@router.patch("/exchanges/{record_id}", response_model=FxTransactionRead)
def update_fx_transaction(
    record_id: int,
    payload: FxTransactionUpdate,
    db: Session = Depends(get_db),
) -> FxTransactionRead:
    user = get_or_create_single_user(db)
    record = exchange_service.update_fx_transaction(db, user.id, record_id, payload)
    return to_fx_transaction_read(record)


@router.delete("/exchanges/{record_id}")
def delete_fx_transaction(
    record_id: int,
    db: Session = Depends(get_db),
) -> dict:
    user = get_or_create_single_user(db)
    exchange_service.delete_fx_transaction(db, user.id, record_id)
    return {"status": "ok"}
