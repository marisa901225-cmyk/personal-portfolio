from __future__ import annotations
from typing import List
from sqlalchemy.orm import Session
from fastapi import HTTPException

from ..core.models import ExternalCashflow
from ..core.schemas import ExternalCashflowCreate, ExternalCashflowUpdate

def get_cashflows(db: Session, user_id: int) -> List[ExternalCashflow]:
    return (
        db.query(ExternalCashflow)
        .filter(ExternalCashflow.user_id == user_id)
        .order_by(ExternalCashflow.date.desc())
        .all()
    )

def create_cashflow(db: Session, user_id: int, item: ExternalCashflowCreate) -> ExternalCashflow:
    db_item = ExternalCashflow(
        user_id=user_id,
        date=item.date,
        amount=item.amount,
        description=item.description,
        account_info=item.account_info
    )
    db.add(db_item)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_item)
    return db_item

def update_cashflow(
    db: Session, 
    user_id: int, 
    cashflow_id: int, 
    item: ExternalCashflowUpdate
) -> ExternalCashflow:
    db_item = db.query(ExternalCashflow).filter(
        ExternalCashflow.id == cashflow_id, 
        ExternalCashflow.user_id == user_id
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Cashflow entry not found")
    
    for key, value in item.model_dump(exclude_unset=True).items():
        setattr(db_item, key, value)
    
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(db_item)
    return db_item

def delete_cashflow(db: Session, user_id: int, cashflow_id: int) -> bool:
    db_item = db.query(ExternalCashflow).filter(
        ExternalCashflow.id == cashflow_id, 
        ExternalCashflow.user_id == user_id
    ).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Cashflow entry not found")
    
    db.delete(db_item)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True
