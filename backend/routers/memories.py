"""
User Memory API - AI 장기 메모리 저장/조회/수정/삭제
"""
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.db import get_db
from ..core.models import UserMemory

router = APIRouter(prefix="/memories", tags=["Memories"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MemoryCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    category: str = Field(default="general", pattern="^(profile|preference|project|fact|general)$")
    key: Optional[str] = Field(default=None, max_length=100)
    importance: int = Field(default=1, ge=1, le=5)
    ttl_days: int = Field(default=0, ge=0)  # 0 = 영구 보관


class MemoryUpdate(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=2000)
    category: Optional[str] = Field(None, pattern="^(profile|preference|project|fact|general)$")
    key: Optional[str] = Field(None, max_length=100)
    importance: Optional[int] = Field(None, ge=1, le=5)
    ttl_days: Optional[int] = Field(None, ge=0)


class MemoryResponse(BaseModel):
    id: int
    content: str
    category: str
    key: Optional[str]
    importance: int
    expires_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MemorySearchRequest(BaseModel):
    """검색용 스키마 (AI 에이전트에서 컨텍스트 조회 시 사용)"""
    query: Optional[str] = None
    category: Optional[str] = None
    min_importance: int = Field(default=1, ge=1, le=5)
    limit: int = Field(default=20, ge=1, le=100)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Routes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@router.get("/", response_model=List[MemoryResponse])
async def list_memories(
    category: Optional[str] = Query(None, pattern="^(profile|preference|project|fact|general)$"),
    min_importance: int = Query(1, ge=1, le=5),
    include_expired: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """모든 메모리 조회 (필터링/페이지네이션 지원)"""
    user_id = 1  # 싱글유저
    
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    
    if category:
        stmt = stmt.where(UserMemory.category == category)
    
    stmt = stmt.where(UserMemory.importance >= min_importance)
    
    if not include_expired:
        stmt = stmt.where(
            (UserMemory.expires_at == None) | (UserMemory.expires_at > datetime.utcnow())
        )
    
    stmt = stmt.order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc())
    stmt = stmt.offset(offset).limit(limit)
    
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
):
    """특정 메모리 조회"""
    user_id = 1
    
    stmt = select(UserMemory).where(
        UserMemory.id == memory_id,
        UserMemory.user_id == user_id
    )
    result = await db.execute(stmt)
    memory = result.scalar_one_or_none()
    
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return memory


@router.post("/", response_model=MemoryResponse, status_code=201)
async def create_memory(
    data: MemoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """새 메모리 생성 (key가 동일하면 기존 것 업데이트)"""
    user_id = 1
    
    # key가 있으면 기존 메모리 찾기
    if data.key:
        stmt = select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.key == data.key
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # 기존 메모리 업데이트
            existing.content = data.content
            existing.category = data.category
            existing.importance = data.importance
            existing.updated_at = datetime.utcnow()
            
            if data.ttl_days > 0:
                existing.expires_at = datetime.utcnow() + timedelta(days=data.ttl_days)
            else:
                existing.expires_at = None
            
            await db.commit()
            await db.refresh(existing)
            return existing
    
    # 새 메모리 생성
    expires_at = None
    if data.ttl_days > 0:
        expires_at = datetime.utcnow() + timedelta(days=data.ttl_days)
    
    memory = UserMemory(
        user_id=user_id,
        content=data.content,
        category=data.category,
        key=data.key,
        importance=data.importance,
        expires_at=expires_at,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    
    return memory


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: int,
    data: MemoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """메모리 수정"""
    user_id = 1
    
    stmt = select(UserMemory).where(
        UserMemory.id == memory_id,
        UserMemory.user_id == user_id
    )
    result = await db.execute(stmt)
    memory = result.scalar_one_or_none()
    
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    if data.content is not None:
        memory.content = data.content
    if data.category is not None:
        memory.category = data.category
    if data.key is not None:
        memory.key = data.key
    if data.importance is not None:
        memory.importance = data.importance
    if data.ttl_days is not None:
        if data.ttl_days > 0:
            memory.expires_at = datetime.utcnow() + timedelta(days=data.ttl_days)
        else:
            memory.expires_at = None
    
    memory.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(memory)
    
    return memory


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
):
    """메모리 삭제"""
    user_id = 1
    
    stmt = select(UserMemory).where(
        UserMemory.id == memory_id,
        UserMemory.user_id == user_id
    )
    result = await db.execute(stmt)
    memory = result.scalar_one_or_none()
    
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    await db.delete(memory)
    await db.commit()


@router.post("/search", response_model=List[MemoryResponse])
async def search_memories(
    req: MemorySearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """메모리 검색 (AI 에이전트용 컨텍스트 조회)"""
    user_id = 1
    
    stmt = select(UserMemory).where(
        UserMemory.user_id == user_id,
        UserMemory.importance >= req.min_importance,
        (UserMemory.expires_at == None) | (UserMemory.expires_at > datetime.utcnow())
    )
    
    if req.category:
        stmt = stmt.where(UserMemory.category == req.category)
    
    if req.query:
        # SQLite LIKE 검색 (한글 지원)
        stmt = stmt.where(UserMemory.content.ilike(f"%{req.query}%"))
    
    stmt = stmt.order_by(UserMemory.importance.desc(), UserMemory.updated_at.desc())
    stmt = stmt.limit(req.limit)
    
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/", status_code=204)
async def cleanup_expired(
    db: AsyncSession = Depends(get_db),
):
    """만료된 메모리 일괄 삭제"""
    user_id = 1
    
    stmt = delete(UserMemory).where(
        UserMemory.user_id == user_id,
        UserMemory.expires_at != None,
        UserMemory.expires_at < datetime.utcnow()
    )
    
    await db.execute(stmt)
    await db.commit()
