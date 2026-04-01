from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..core.models import SpamRule
from ..core.time_utils import utcnow


@dataclass(frozen=True)
class SpamRuleCreatePayload:
    rule_type: str
    pattern: str
    category: str = "general"
    note: str | None = None


def list_spam_rules(db: Session) -> list[SpamRule]:
    return db.query(SpamRule).order_by(SpamRule.id).all()


def create_spam_rule(
    db: Session,
    *,
    rule_type: str,
    pattern: str,
    category: str = "general",
    note: str | None = None,
) -> SpamRule:
    new_rule = SpamRule(
        rule_type=rule_type,
        pattern=pattern,
        category=category,
        note=note,
        is_enabled=True,
        created_at=utcnow(),
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return new_rule


def create_spam_rules_from_patterns(
    db: Session,
    patterns: Iterable[str],
    *,
    note: str = "텔레그램 추가",
) -> list[SpamRule]:
    created: list[SpamRule] = []
    for pattern in patterns:
        created.append(
            create_spam_rule(
                db,
                rule_type="contains",
                pattern=pattern,
                category="general",
                note=note,
            )
        )
    return created


def get_spam_rule_or_404(db: Session, rule_id: int) -> SpamRule:
    rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


def delete_spam_rule(db: Session, rule_id: int) -> None:
    rule = get_spam_rule_or_404(db, rule_id)
    db.delete(rule)
    db.commit()


def toggle_spam_rule(db: Session, rule_id: int) -> SpamRule:
    rule = get_spam_rule_or_404(db, rule_id)
    rule.is_enabled = not rule.is_enabled
    db.commit()
    db.refresh(rule)
    return rule


def set_spam_rule_enabled(db: Session, rule_id: int, enabled: bool) -> SpamRule:
    rule = get_spam_rule_or_404(db, rule_id)
    rule.is_enabled = enabled
    db.commit()
    db.refresh(rule)
    return rule


def get_recent_spam_rules(db: Session, limit: int = 30) -> list[SpamRule]:
    return db.query(SpamRule).order_by(SpamRule.id.desc()).limit(limit).all()
