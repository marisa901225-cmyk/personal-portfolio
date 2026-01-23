"""
Expense Classifier

가맹점 분류 및 AI 모델 관련 로직.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    from sklearn.base import BaseEstimator  # type: ignore

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...core.models import Expense, MerchantPattern
from ...services.users import get_or_create_single_user


# --- Constants ---
_INCOME_MERCHANT_KEYWORDS = (
    "급여", "salary", "월급", "입금", "캐시백", "포인트", "이자", "환급",
)
_REVIEW_CONFIDENCE_THRESHOLD = 0.65
_EXPENSE_MODEL_PATH = Path(__file__).resolve().parents[2] / "data" / "expense_model.joblib"
_EXPENSE_MODEL_CACHE: Any | None = None  # sklearn model
_EXPENSE_MODEL_MTIME: float | None = None
_EXPENSE_MODEL_LOAD_ERR_ONCE = False


def load_expense_model() -> Any | None:
    """캐시된 AI 분류 모델 로드."""
    global _EXPENSE_MODEL_CACHE, _EXPENSE_MODEL_MTIME, _EXPENSE_MODEL_LOAD_ERR_ONCE
    
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
        _EXPENSE_MODEL_LOAD_ERR_ONCE = False
        return _EXPENSE_MODEL_CACHE
    except Exception as e:
        if not _EXPENSE_MODEL_LOAD_ERR_ONCE:
            _EXPENSE_MODEL_LOAD_ERR_ONCE = True
            import logging
            logging.getLogger(__name__).warning("Expense model load failed: %s", e)
        _EXPENSE_MODEL_CACHE = None
        _EXPENSE_MODEL_MTIME = None
        return None


def is_income_merchant(merchant: str) -> bool:
    """가맹점명이 수입 관련인지 판단."""
    merchant_lower = merchant.lower()
    return any(keyword in merchant_lower for keyword in _INCOME_MERCHANT_KEYWORDS)


def build_review_info(
    expense: Expense,
    learned_patterns: dict[str, str],
    model: Any | None,  # sklearn model
) -> tuple[str, str | None] | None:
    """AI 리뷰 정보 생성 (변경 제안 등)."""
    if expense.amount >= 0:
        return None
    if not expense.merchant:
        return None

    merchant = expense.merchant.strip()
    if not merchant or is_income_merchant(merchant):
        return None

    pattern_category = learned_patterns.get(merchant)
    if pattern_category and pattern_category not in {"급여", "기타수입"}:
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

    if expense.category == str(predicted):
        return None

    return (f"AI 추정: {predicted} (신뢰 {confidence:.2f})", str(predicted))


def learn_patterns_from_history(db: Session) -> dict:
    """기존 모든 소비 내역을 분석하여 가맹점별 최빈 카테고리를 학습."""
    user = get_or_create_single_user(db)
    
    stats = (
        db.query(Expense.merchant, Expense.category, func.count(Expense.id).label("count"))
        .filter(
            Expense.user_id == user.id,
            Expense.amount < 0,
            Expense.merchant.isnot(None),
            Expense.merchant != '',
            Expense.deleted_at.is_(None),
        )
        .group_by(Expense.merchant, Expense.category)
        .all()
    )
    
    merchant_top_cat: dict[str, str] = {}
    merchant_top_count: dict[str, int] = {}
    
    for merchant, category, count in stats:
        m_stripped = merchant.strip()
        if count > merchant_top_count.get(m_stripped, 0):
            merchant_top_count[m_stripped] = count
            merchant_top_cat[m_stripped] = category

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
        
    ai_success = False
    try:
        from ...services.expense_trainer import train_model
        ai_success = train_model()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("AI 모델 학습 중 오류 발생: %s", e)

    return {"status": "ok", "added": added, "updated": updated, "ai_trained": ai_success}
