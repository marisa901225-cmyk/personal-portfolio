from __future__ import annotations

from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


def get_owned_row_or_404(
    db: Session,
    model: type[ModelT],
    row_id: int,
    user_id: int,
    *,
    detail: str,
) -> ModelT:
    row = db.query(model).filter(model.id == row_id, model.user_id == user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail=detail)
    return row


def commit_with_refresh(db: Session, row: Any) -> Any:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return row


def commit_or_rollback(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
