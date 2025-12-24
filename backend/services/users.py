from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import User


def get_or_create_single_user(db: Session) -> User:
    user = db.query(User).first()
    if user:
        return user
    user = User(name="default")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

