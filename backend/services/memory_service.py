from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, List

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from ..core.models import UserMemory
from ..core.time_utils import utcnow


def list_memories(
    db: Session,
    user_id: int = 1,
    category: Optional[str] = None,
    min_importance: int = 1,
    include_expired: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> List[UserMemory]:
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    if category:
        stmt = stmt.where(UserMemory.category == category)
    stmt = stmt.where(UserMemory.importance >= min_importance)
    if not include_expired:
        stmt = stmt.where(
            (UserMemory.expires_at == None) | (UserMemory.expires_at > utcnow())
        )
    stmt = stmt.order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc())
    stmt = stmt.offset(offset).limit(limit)
    result = db.execute(stmt)
    return list(result.scalars().all())


def get_memory(
    db: Session,
    memory_id: int,
    user_id: int = 1,
) -> Optional[UserMemory]:
    stmt = select(UserMemory).where(
        UserMemory.id == memory_id,
        UserMemory.user_id == user_id
    )
    result = db.execute(stmt)
    return result.scalar_one_or_none()


def create_or_update_memory(
    db: Session,
    user_id: int,
    content: str,
    category: str = "general",
    key: Optional[str] = None,
    importance: int = 1,
    ttl_days: int = 0,
) -> UserMemory:
    # key가 있으면 기존 메모리 찾기
    if key:
        stmt = select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == key
        )
        result = db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            existing.content = content
            existing.category = category
            existing.importance = importance
            existing.updated_at = utcnow()
            if ttl_days > 0:
                existing.expires_at = utcnow() + timedelta(days=ttl_days)
            else:
                existing.expires_at = None
            db.commit()
            db.refresh(existing)
            return existing

    # 새 메모리 생성
    expires_at = None
    if ttl_days > 0:
        expires_at = utcnow() + timedelta(days=ttl_days)
    memory = UserMemory(
        user_id=user_id,
        content=content,
        category=category,
        key=key,
        importance=importance,
        expires_at=expires_at,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def update_memory(
    db: Session,
    memory_id: int,
    user_id: int,
    content: Optional[str] = None,
    category: Optional[str] = None,
    key: Optional[str] = None,
    importance: Optional[int] = None,
    ttl_days: Optional[int] = None,
) -> Optional[UserMemory]:
    memory = get_memory(db, memory_id, user_id)
    if not memory:
        return None
    if content is not None:
        memory.content = content
    if category is not None:
        memory.category = category
    if key is not None:
        memory.key = key
    if importance is not None:
        memory.importance = importance
    if ttl_days is not None:
        if ttl_days > 0:
            memory.expires_at = utcnow() + timedelta(days=ttl_days)
        else:
            memory.expires_at = None
    memory.updated_at = utcnow()
    db.commit()
    db.refresh(memory)
    return memory


def delete_memory(
    db: Session,
    memory_id: int,
    user_id: int = 1,
) -> bool:
    memory = get_memory(db, memory_id, user_id)
    if not memory:
        return False
    db.delete(memory)
    db.commit()
    return True


def search_memories(
    db: Session,
    user_id: int = 1,
    query: Optional[str] = None,
    category: Optional[str] = None,
    min_importance: int = 1,
    limit: int = 20,
) -> List[UserMemory]:
    stmt = select(UserMemory).where(
        UserMemory.user_id == user_id,
        UserMemory.importance >= min_importance,
        (UserMemory.expires_at == None) | (UserMemory.expires_at > utcnow())
    )
    if category:
        stmt = stmt.where(UserMemory.category == category)
    if query:
        stmt = stmt.where(UserMemory.content.ilike(f"%{query}%"))
    stmt = stmt.order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc())
    stmt = stmt.limit(limit)
    result = db.execute(stmt)
    return list(result.scalars().all())


def cleanup_expired_memories(
    db: Session,
    user_id: int = 1,
) -> None:
    stmt = delete(UserMemory).where(
        UserMemory.user_id == user_id,
        UserMemory.expires_at != None,
        UserMemory.expires_at < utcnow()
    )
    db.execute(stmt)
    db.commit()
