"""Expense router for consumption data tracking."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.schemas import ExpenseCreate, ExpenseRead, ExpenseUpdate
from ..services import expense_service

router = APIRouter(prefix="/api/expenses", tags=["expenses"], dependencies=[Depends(verify_api_token)])


@router.get("/categories", response_model=List[str])
def get_categories(db: Session = Depends(get_db)) -> List[str]:
    """사용자가 사용한 모든 고유 카테고리 목록 조회."""
    return expense_service.get_categories(db)


@router.get("/", response_model=List[ExpenseRead])
def get_expenses(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    category: str | None = Query(None),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
) -> List[dict]:
    """소비 내역 조회. 년/월/카테고리 필터 지원."""
    return expense_service.get_expenses_with_review(
        db, year=year, month=month, category=category, include_deleted=include_deleted
    )


@router.post("/", response_model=ExpenseRead)
def create_expense(
    payload: ExpenseCreate,
    db: Session = Depends(get_db),
) -> ExpenseRead:
    """새 소비 내역 추가."""
    return expense_service.create_expense(db, payload)


@router.patch("/{expense_id}", response_model=ExpenseRead)
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    db: Session = Depends(get_db),
) -> ExpenseRead:
    """소비 내역 수정."""
    return expense_service.update_expense(db, expense_id, payload)


@router.post("/learn")
def learn_patterns_from_history(db: Session = Depends(get_db)) -> dict:
    """기존 모든 소비 내역을 분석하여 가맹점별 최빈 카테고리를 학습."""
    return expense_service.learn_patterns_from_history(db)


@router.delete("/{expense_id}")
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """소비 내역 소프트 삭제."""
    return expense_service.delete_expense(db, expense_id)


@router.post("/{expense_id}/restore", response_model=ExpenseRead)
def restore_expense(
    expense_id: int,
    db: Session = Depends(get_db),
) -> ExpenseRead:
    """소비 내역 복구."""
    return expense_service.restore_expense(db, expense_id)


@router.get("/summary")
def get_expense_summary_endpoint(
    year: int | None = Query(None, ge=1970),
    month: int | None = Query(None, ge=1, le=12),
    db: Session = Depends(get_db),
) -> dict:
    """소비 내역 요약 (카테고리별 합계, 고정지출 비율 등)."""
    return expense_service.get_expense_summary(db, year, month)
