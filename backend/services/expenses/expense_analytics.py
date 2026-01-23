"""
Expense Analytics

지출/수입 통계 및 분석 로직.
"""
from __future__ import annotations

from sqlalchemy import extract
from sqlalchemy.orm import Session

from ...core.models import Expense
from ...services.users import get_or_create_single_user


def get_expense_summary(
    db: Session,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """소비 내역 요약을 생성한다."""
    user = get_or_create_single_user(db)

    query = db.query(Expense).filter(Expense.user_id == user.id, Expense.deleted_at.is_(None))

    if year is not None:
        query = query.filter(extract("year", Expense.date) == year)
        if month is not None:
            query = query.filter(extract("month", Expense.date) == month)

    expenses = query.all()

    total_expense = sum(e.amount for e in expenses if e.amount < 0)
    total_income = sum(e.amount for e in expenses if e.amount >= 0)
    fixed_expense = sum(e.amount for e in expenses if e.is_fixed and e.amount < 0)

    category_summary: dict[str, float] = {}
    for e in expenses:
        if e.amount < 0:
            if e.category not in category_summary:
                category_summary[e.category] = 0
            category_summary[e.category] += abs(e.amount)

    method_summary: dict[str, float] = {}
    for e in expenses:
        if e.amount < 0 and e.method:
            if e.method not in method_summary:
                method_summary[e.method] = 0
            method_summary[e.method] += abs(e.amount)

    return {
        "period": {"year": year, "month": month},
        "total_expense": abs(total_expense),
        "total_income": total_income,
        "net": total_income + total_expense,
        "fixed_expense": abs(fixed_expense),
        "fixed_ratio": abs(fixed_expense / total_expense) * 100 if total_expense != 0 else 0,
        "category_breakdown": [
            {"category": k, "amount": v}
            for k, v in sorted(category_summary.items(), key=lambda x: x[1], reverse=True)
        ],
        "method_breakdown": [
            {"method": k, "amount": v}
            for k, v in sorted(method_summary.items(), key=lambda x: x[1], reverse=True)
        ],
        "transaction_count": len(expenses),
    }
