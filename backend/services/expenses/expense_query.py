from __future__ import annotations

from sqlalchemy import extract
from sqlalchemy.orm import Query, Session

from ...core.models import Expense
from ...services.users import get_or_create_single_user


def build_user_expense_query(
    db: Session,
    *,
    include_deleted: bool = False,
    year: int | None = None,
    month: int | None = None,
    category: str | None = None,
) -> Query[Expense]:
    """사용자 범위의 지출 쿼리를 공통 조건으로 조립한다."""
    user = get_or_create_single_user(db)

    query = db.query(Expense).filter(Expense.user_id == user.id)
    if not include_deleted:
        query = query.filter(Expense.deleted_at.is_(None))

    if year is not None:
        query = query.filter(extract("year", Expense.date) == year)
        if month is not None:
            query = query.filter(extract("month", Expense.date) == month)

    if category is not None:
        query = query.filter(Expense.category == category)

    return query
