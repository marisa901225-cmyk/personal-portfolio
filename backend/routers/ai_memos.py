from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.models import AiMemo
from ..services.users import get_or_create_single_user

DEFAULT_MEMO_TITLE = "새 메모"

router = APIRouter(
    prefix="/api/ai-memos",
    tags=["AI Memos"],
    dependencies=[Depends(verify_api_token)],
)


class AiMemoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime


class AiMemoCreate(BaseModel):
    title: str = Field(default=DEFAULT_MEMO_TITLE, min_length=1, max_length=200)
    content: str = Field(default="", max_length=100000)


class AiMemoUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, max_length=100000)


def _get_user_memo(db: Session, user_id: int, memo_id: int) -> AiMemo:
    memo = (
        db.query(AiMemo)
        .filter(AiMemo.id == memo_id, AiMemo.user_id == user_id)
        .first()
    )
    if memo is None:
        raise HTTPException(status_code=404, detail="Memo not found")
    return memo


@router.get("/", response_model=List[AiMemoRead])
def list_ai_memos(db: Session = Depends(get_db)) -> list[AiMemo]:
    user = get_or_create_single_user(db)
    return (
        db.query(AiMemo)
        .filter(AiMemo.user_id == user.id)
        .order_by(AiMemo.updated_at.desc(), AiMemo.id.desc())
        .all()
    )


@router.post("/", response_model=AiMemoRead)
def create_ai_memo(
    payload: AiMemoCreate,
    db: Session = Depends(get_db),
) -> AiMemo:
    user = get_or_create_single_user(db)
    memo = AiMemo(user_id=user.id, title=payload.title.strip(), content=payload.content)
    db.add(memo)
    db.commit()
    db.refresh(memo)
    return memo


@router.patch("/{memo_id}", response_model=AiMemoRead)
def update_ai_memo(
    memo_id: int,
    payload: AiMemoUpdate,
    db: Session = Depends(get_db),
) -> AiMemo:
    user = get_or_create_single_user(db)
    memo = _get_user_memo(db, user.id, memo_id)
    if payload.title is not None:
        memo.title = payload.title.strip()
    if payload.content is not None:
        memo.content = payload.content
    db.commit()
    db.refresh(memo)
    return memo


@router.delete("/{memo_id}")
def delete_ai_memo(memo_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    user = get_or_create_single_user(db)
    memo = _get_user_memo(db, user.id, memo_id)
    db.delete(memo)
    db.commit()
    return {"message": "Memo deleted"}
