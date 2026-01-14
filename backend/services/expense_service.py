"""
Expense Service

지출/수입 관련 비즈니스 로직.
라우터 간 의존을 제거하기 위해 서비스 레이어로 분리.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, List

from fastapi import HTTPException
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from ..core.models import Expense, MerchantPattern
from ..core.schemas import ExpenseCreate, ExpenseUpdate
from ..services.users import get_or_create_single_user

# --- Constants & Global State (Migrated from Router) ---
_INCOME_MERCHANT_KEYWORDS = (
    "급여",
    "salary",
    "월급",
    "입금",
    "캐시백",
    "포인트",
    "이자",
    "환급",
)
_REVIEW_CONFIDENCE_THRESHOLD = 0.65
_EXPENSE_MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "expense_model.joblib"
_EXPENSE_MODEL_CACHE: Any | None = None
_EXPENSE_MODEL_MTIME: float | None = None


# --- Helper Methods ---

def _load_expense_model() -> Any | None:
    global _EXPENSE_MODEL_CACHE, _EXPENSE_MODEL_MTIME

    if not _EXPENSE_MODEL_PATH.exists():
        _EXPENSE_MODEL_CACHE = None
        _EXPENSE_MODEL_MTIME = None
        return None

    mtime = _EXPENSE_MODEL_PATH.stat().st_mtime
    if _EXPENSE_MODEL_CACHE is not None and _EXPENSE_MODEL_MTIME == mtime:
        return _EXPENSE_MODEL_CACHE

    try:
        import joblib
        _EXPENSE_MODEL_CACHE = joblib.load(_EXPENSE_MODEL_PATH)
        _EXPENSE_MODEL_MTIME = mtime
        return _EXPENSE_MODEL_CACHE
    except Exception:
        _EXPENSE_MODEL_CACHE = None
        _EXPENSE_MODEL_MTIME = None
        return None


def _is_income_merchant(merchant: str) -> bool:
    merchant_lower = merchant.lower()
    return any(keyword in merchant_lower for keyword in _INCOME_MERCHANT_KEYWORDS)


def _build_review_info(
    expense: Expense,
    learned_patterns: dict[str, str],
    model: Any | None,
) -> tuple[str, str | None] | None:
    # Skip income (positive amounts), only review expenses (negative amounts)
    if expense.amount >= 0:
        return None
    if not expense.merchant:
        return None

    merchant = expense.merchant.strip()
    if not merchant or _is_income_merchant(merchant):
        return None

    pattern_category = learned_patterns.get(merchant)
    if pattern_category and pattern_category not in {"급여", "기타수입"}:
        # 패턴이 현재 카테고리와 다를 때만 검토 필요 표시
        if expense.category != pattern_category:
            return (f"학습된 패턴: {pattern_category}", pattern_category)

    if model is None or not hasattr(model, "predict"):
        return None

    try:
        predicted = model.predict([merchant])[0]
    except Exception:
        return None

    confidence = None
    if hasattr(model, "predict_proba"):
        try:
            proba = model.predict_proba([merchant])[0]
            confidence = float(max(proba))
        except Exception:
            confidence = None

    if confidence is None or confidence < _REVIEW_CONFIDENCE_THRESHOLD:
        return None

    # AI 추정이 현재 카테고리와 다를 때만 검토 필요 표시
    if expense.category == str(predicted):
        return None

    return (f"AI 추정: {predicted} (신뢰 {confidence:.2f})", str(predicted))


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

    query = db.query(Expense).filter(Expense.user_id == user.id)
    if not include_deleted:
        query = query.filter(Expense.deleted_at.is_(None))

    if year is not None:
        query = query.filter(extract("year", Expense.date) == year)
        if month is not None:
            query = query.filter(extract("month", Expense.date) == month)

    if category is not None:
        query = query.filter(Expense.category == category)

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
    # while adding the extra review fields.
    from ..core.schemas import ExpenseRead # Imported locally to avoid circulars if any, though likely fine at top
    
    for expense in expenses:
        # Pydantic model conversion happens here to get a dict, or we can just pass the ORM object 
        # but custom logical fields need to be handled.
        # Ideally service returns domain objects or Pydantic models.
        # Let's return the Pydantic model dump with extra fields injected.
        
        payload = ExpenseRead.model_validate(expense).model_dump()
        review_info = _build_review_info(expense, learned_patterns, model)
        if review_info:
            review_reason, review_category = review_info
            payload["review_reason"] = review_reason
            payload["review_suggested_category"] = review_category
        results.append(payload)
        
    return results


def get_expense_summary(
    db: Session,
    year: int | None = None,
    month: int | None = None,
) -> dict:
    """
    소비 내역 요약을 생성한다.
    """
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
        if e.amount < 0:  # 지출만
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
    expense.updated_at = datetime.utcnow()

    try:
        # 카테고리가 변경되었다면 학습 패턴 업데이트
        if payload.category and expense.merchant:
            pattern = (
                db.query(MerchantPattern)
                .filter(MerchantPattern.user_id == user.id, MerchantPattern.merchant == expense.merchant)
                .first()
            )
            if pattern:
                pattern.category = payload.category
            else:
                pattern = MerchantPattern(
                    user_id=user.id,
                    merchant=expense.merchant,
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
        expense.deleted_at = datetime.utcnow()
        expense.updated_at = datetime.utcnow()
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
    expense.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(expense)
    return expense


def learn_patterns_from_history(db: Session) -> dict:
    """기존 모든 소비 내역을 분석하여 가맹점별 최빈 카테고리를 학습."""
    user = get_or_create_single_user(db)
    
    # 가맹점별 카테고리 빈도 분석
    stats = (
        db.query(Expense.merchant, Expense.category, func.count(Expense.id).label("count"))
        .filter(
            Expense.user_id == user.id,
            Expense.amount < 0,
            Expense.merchant != None,
            Expense.merchant != '',
            Expense.deleted_at.is_(None),
        )
        .group_by(Expense.merchant, Expense.category)
        .all()
    )
    
    # 가맹점마다 가장 많이 쓰인 카테고리 추출
    merchant_top_cat = {}
    merchant_counts = {} # (merchant, category) -> count
    
    for merchant, category, count in stats:
        if merchant not in merchant_top_cat or count > merchant_counts.get((merchant, merchant_top_cat.get(merchant, "")), 0):
            merchant_top_cat[merchant] = category
            merchant_counts[(merchant, category)] = count

    # MerchantPattern 테이블 업데이트
    added = 0
    updated = 0
    for merchant, category in merchant_top_cat.items():
        pattern = (
            db.query(MerchantPattern)
            .filter(MerchantPattern.user_id == user.id, MerchantPattern.merchant == merchant)
            .first()
        )
        if pattern:
            if pattern.category != category:
                pattern.category = category
                updated += 1
        else:
            pattern = MerchantPattern(
                user_id=user.id,
                merchant=merchant,
                category=category
            )
            db.add(pattern)
            added += 1
            
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
        
    # AI 모델 학습 추가
    ai_success = False
    try:
        from ..services.expense_trainer import train_model
        ai_success = train_model()
    except Exception as e:
        print(f"⚠️ AI 모델 학습 중 오류 발생: {e}")

    return {
        "status": "ok", 
        "added": added, 
        "updated": updated, 
        "ai_trained": ai_success
    }
