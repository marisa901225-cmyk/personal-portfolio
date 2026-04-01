"""
Expense Service

지출/수입 관련 CRUD 비즈니스 로직.
분류/학습은 expenses.expense_classifier, 통계는 expenses.expense_analytics 참조.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..core.models import Expense, MerchantPattern
from ..core.schemas import ExpenseCreate, ExpenseUpdate
from ..services.users import get_or_create_single_user

# Import refactored modules
from .expenses.expense_analytics import get_expense_summary
from .expenses.expense_classifier import (
    load_expense_model as _load_expense_model,
    is_income_merchant as _is_income_merchant,
    build_review_info as _build_review_info,
    learn_patterns_from_history,
)
from .expenses.expense_query import build_user_expense_query

# Re-export for backward compatibility
__all__ = [
    "get_categories",
    "get_expenses_with_review",
    "get_expense_summary",
    "create_expense",
    "update_expense",
    "delete_expense",
    "restore_expense",
    "learn_patterns_from_history",
]


# --- Read Operations ---



def get_categories(db: Session) -> List[str]:
    """사용자가 사용한 모든 고유 카테고리 목록 조회."""
    user = get_or_create_single_user(db)
    results = (
        db.query(Expense.category)
        .filter(Expense.user_id == user.id, Expense.deleted_at.is_(None))
        .distinct()
        .all()
    )
    return sorted([r[0] for r in results if r[0]])


def get_expenses_with_review(
    db: Session,
    year: int | None = None,
    month: int | None = None,
    category: str | None = None,
    include_deleted: bool = False,
) -> List[dict]:
    """소비 내역 조회 및 AI 리뷰 정보 부착."""
    user = get_or_create_single_user(db)
    query = build_user_expense_query(
        db,
        include_deleted=include_deleted,
        year=year,
        month=month,
        category=category,
    )
    expenses = query.order_by(Expense.date.desc()).all()

    # AI Model & Patterns Preparation
    learned_patterns = {
        merchant.strip(): category
        for merchant, category in db.query(MerchantPattern.merchant, MerchantPattern.category)
        .filter(MerchantPattern.user_id == user.id)
        .all()
        if merchant
    }
    model = _load_expense_model()

    results: list[dict] = []
    # Note: We return dicts here to allow the router to easily validate against ExpenseRead
    from ..core.schemas import ExpenseRead # Moved outside the loop
    
    for expense in expenses:
        payload = ExpenseRead.model_validate(expense).model_dump()
        review_info = _build_review_info(expense, learned_patterns, model)
        if review_info:
            review_reason, review_category = review_info
            payload["review_reason"] = review_reason
            payload["review_suggested_category"] = review_category
        results.append(payload)
        
    return results


# --- Write Operations ---

def create_expense(db: Session, payload: ExpenseCreate) -> Expense:
    """새 소비 내역 추가."""
    user = get_or_create_single_user(db)

    expense = Expense(
        user_id=user.id,
        date=payload.date,
        amount=payload.amount,
        category=payload.category,
        merchant=payload.merchant,
        method=payload.method,
        is_fixed=payload.is_fixed,
        memo=payload.memo,
    )
    db.add(expense)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(expense)
    return expense


def update_expense(db: Session, expense_id: int, payload: ExpenseUpdate) -> Expense:
    """소비 내역 수정."""
    user = get_or_create_single_user(db)

    expense = (
        db.query(Expense)
        .filter(
            Expense.id == expense_id,
            Expense.user_id == user.id,
            Expense.deleted_at.is_(None),
        )
        .first()
    )
    if not expense:
        raise HTTPException(status_code=404, detail="expense not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(expense, field, value)
    expense.updated_at = datetime.now(timezone.utc)

    try:
        # 카테고리가 변경되었다면 학습 패턴 업데이트
        if payload.category and expense.merchant:
            merchant = expense.merchant.strip()
            expense.merchant = merchant
            pattern = (
                db.query(MerchantPattern)
                .filter(MerchantPattern.user_id == user.id, MerchantPattern.merchant == merchant)
                .first()
            )
            if pattern:
                pattern.category = payload.category
            else:
                pattern = MerchantPattern(
                    user_id=user.id,
                    merchant=merchant,
                    category=payload.category
                )
                db.add(pattern)
        
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(expense)
    return expense


def delete_expense(db: Session, expense_id: int) -> dict:
    """소비 내역 소프트 삭제."""
    user = get_or_create_single_user(db)

    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.user_id == user.id)
        .first()
    )
    if not expense:
        raise HTTPException(status_code=404, detail="expense not found")

    if expense.deleted_at is None:
        expense.deleted_at = datetime.now(timezone.utc)
        expense.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"status": "ok", "deleted_at": expense.deleted_at.isoformat() if expense.deleted_at else None}


def restore_expense(db: Session, expense_id: int) -> Expense:
    """소비 내역 복구."""
    user = get_or_create_single_user(db)

    expense = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.user_id == user.id)
        .first()
    )
    if not expense:
        raise HTTPException(status_code=404, detail="expense not found")

    expense.deleted_at = None
    expense.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(expense)
    return expense
