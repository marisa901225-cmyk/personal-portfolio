"""
Spam Rules Router - 스팸 규칙 CRUD API
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.models import SpamRule
from ..core.time_utils import utcnow

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
    return db.query(SpamRule).order_by(SpamRule.id).all()


@router.post("", response_model=SpamRuleResponse)
def create_spam_rule(rule: SpamRuleCreate, db: Session = Depends(get_db)):
    """스팸 규칙 추가"""
    new_rule = SpamRule(
        rule_type=rule.rule_type,
        pattern=rule.pattern,
        category=rule.category,
        note=rule.note,
        is_enabled=True,
        created_at=utcnow()
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return new_rule


@router.delete("/{rule_id}")
def delete_spam_rule(rule_id: int, db: Session = Depends(get_db)):
    """스팸 규칙 삭제"""
    rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"message": f"Rule {rule_id} deleted"}


@router.patch("/{rule_id}/toggle")
def toggle_spam_rule(rule_id: int, db: Session = Depends(get_db)):
    """스팸 규칙 활성화/비활성화 토글"""
    rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_enabled = not rule.is_enabled
    db.commit()
    return {"id": rule_id, "is_enabled": rule.is_enabled}
