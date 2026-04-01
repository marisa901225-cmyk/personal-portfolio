"""
Spam Rules Router - 스팸 규칙 CRUD API
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..services.spam_rule_service import (
    create_spam_rule as create_spam_rule_record,
    delete_spam_rule as delete_spam_rule_record,
    list_spam_rules as list_spam_rules_record,
    set_spam_rule_enabled,
)

router = APIRouter(
    prefix="/api/spam-rules",
    tags=["spam-rules"],
    dependencies=[Depends(verify_api_token)],
)


class SpamRuleCreate(BaseModel):
    rule_type: str  # 'contains' | 'regex' | 'promo_combo'
    pattern: str
    category: str = "general"
    note: Optional[str] = None


class SpamRuleResponse(BaseModel):
    id: int
    rule_type: str
    pattern: str
    category: str
    note: Optional[str]
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[SpamRuleResponse])
def list_spam_rules(db: Session = Depends(get_db)):
    """스팸 규칙 목록 조회"""
    return list_spam_rules_record(db)


@router.post("", response_model=SpamRuleResponse)
def create_spam_rule(rule: SpamRuleCreate, db: Session = Depends(get_db)):
    """스팸 규칙 추가"""
    return create_spam_rule_record(
        db,
        rule_type=rule.rule_type,
        pattern=rule.pattern,
        category=rule.category,
        note=rule.note,
    )


@router.delete("/{rule_id}")
def delete_spam_rule(rule_id: int, db: Session = Depends(get_db)):
    """스팸 규칙 삭제"""
    delete_spam_rule_record(db, rule_id)
    return {"message": f"Rule {rule_id} deleted"}


@router.patch("/{rule_id}/toggle")
def toggle_spam_rule(rule_id: int, db: Session = Depends(get_db)):
    """스팸 규칙 활성화/비활성화 토글"""
    from ..services.spam_rule_service import get_spam_rule_or_404

    rule = get_spam_rule_or_404(db, rule_id)
    rule = set_spam_rule_enabled(db, rule_id, enabled=not rule.is_enabled)
    return {"id": rule_id, "is_enabled": rule.is_enabled}
