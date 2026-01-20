"""
User Memory API - AI 장기 메모리 저장/조회/수정/삭제
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from ..core.db import get_db
from ..services import memory_service

router = APIRouter(prefix="/api/memories", tags=["Memories"])


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
    return await memory_service.list_memories(
        db=db,
        category=category,
        min_importance=min_importance,
        include_expired=include_expired,
        limit=limit,
        offset=offset
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
):
    """특정 메모리 조회"""
    memory = await memory_service.get_memory(db, memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.post("/", response_model=MemoryResponse, status_code=201)
async def create_memory(
    data: MemoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """새 메모리 생성 (key가 동일하면 기존 것 업데이트)"""
    return await memory_service.create_or_update_memory(
        db=db,
        user_id=1,
        content=data.content,
        category=data.category,
        key=data.key,
        importance=data.importance,
        ttl_days=data.ttl_days
    )


@router.patch("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: int,
    data: MemoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """메모리 수정"""
    memory = await memory_service.update_memory(
        db=db,
        memory_id=memory_id,
        user_id=1,
        content=data.content,
        category=data.category,
        key=data.key,
        importance=data.importance,
        ttl_days=data.ttl_days
    )
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    return memory


@router.delete("/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
):
    """메모리 삭제"""
    success = await memory_service.delete_memory(db, memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")


@router.post("/search", response_model=List[MemoryResponse])
async def search_memories(
    req: MemorySearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """메모리 검색 (AI 에이전트용 컨텍스트 조회)"""
    return await memory_service.search_memories(
        db=db,
        user_id=1,
        query=req.query,
        category=req.category,
        min_importance=req.min_importance,
        limit=req.limit
    )


@router.delete("/", status_code=204)
async def cleanup_expired(
    db: AsyncSession = Depends(get_db),
):
    """만료된 메모리 일괄 삭제"""
    await memory_service.cleanup_expired_memories(db, user_id=1)
