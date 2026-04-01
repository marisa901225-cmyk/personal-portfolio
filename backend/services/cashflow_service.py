from __future__ import annotations
from typing import List
from sqlalchemy.orm import Session

from ..core.models import ExternalCashflow
from ..core.schemas import ExternalCashflowCreate, ExternalCashflowUpdate
from .crud_helpers import commit_or_rollback, commit_with_refresh, get_owned_row_or_404

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
    return commit_with_refresh(db, db_item)

def update_cashflow(
    db: Session, 
    user_id: int, 
    cashflow_id: int, 
    item: ExternalCashflowUpdate
) -> ExternalCashflow:
    db_item = get_owned_row_or_404(
        db,
        ExternalCashflow,
        cashflow_id,
        user_id,
        detail="Cashflow entry not found",
    )
    for key, value in item.model_dump(exclude_unset=True).items():
        setattr(db_item, key, value)
    return commit_with_refresh(db, db_item)

def delete_cashflow(db: Session, user_id: int, cashflow_id: int) -> bool:
    db_item = get_owned_row_or_404(
        db,
        ExternalCashflow,
        cashflow_id,
        user_id,
        detail="Cashflow entry not found",
    )
    db.delete(db_item)
    commit_or_rollback(db)
    return True
