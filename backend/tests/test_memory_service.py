import pytest
import asyncio
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from backend.core.models import Base, User, UserMemory
from backend.services import memory_service
from backend.core.time_utils import utcnow

# 테스트용 인메모리 SQLite (비동기)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="function")
async def async_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()

@pytest.fixture(scope="function")
async def db_session(async_engine):
    async_session = sessionmaker(
        async_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with async_session() as session:
        # 기본 사용자 생성
        user = User(id=1, name="Test User")
        session.add(user)
        await session.commit()
        yield session

@pytest.mark.asyncio
async def test_create_memory_success(db_session):
    content = "Annabeth is my beautiful girlfriend"
    category = "profile"
    
    memory = await memory_service.create_or_update_memory(
        db_session, user_id=1, content=content, category=category, importance=5
    )
    
    assert memory.id is not None
    assert memory.content == content
    assert memory.category == category
    assert memory.importance == 5

@pytest.mark.asyncio
async def test_create_or_update_with_key(db_session):
    key = "daily_routine"
    await memory_service.create_or_update_memory(
        db_session, user_id=1, content="Wake up at 7am", key=key
    )
    
    # 동일 키로 업데이트
    updated = await memory_service.create_or_update_memory(
        db_session, user_id=1, content="Wake up at 8am", key=key
    )
    
    assert updated.content == "Wake up at 8am"
    
    # 전체 개수 확인 (1개여야 함)
    memories = await memory_service.list_memories(db_session, user_id=1)
    assert len(memories) == 1

@pytest.mark.asyncio
async def test_list_memories_filtering(db_session):
    await memory_service.create_or_update_memory(db_session, user_id=1, content="Info 1", category="fact", importance=3)
    await memory_service.create_or_update_memory(db_session, user_id=1, content="Info 2", category="profile", importance=1)
    
    # 중요도 필터링
    m_imp3 = await memory_service.list_memories(db_session, user_id=1, min_importance=3)
    assert len(m_imp3) == 1
    assert m_imp3[0].content == "Info 1"
    
    # 카테고리 필터링
    m_profile = await memory_service.list_memories(db_session, user_id=1, category="profile")
    assert len(m_profile) == 1
    assert m_profile[0].content == "Info 2"

@pytest.mark.asyncio
async def test_search_memories(db_session):
    await memory_service.create_or_update_memory(db_session, user_id=1, content="I like chocolate ice cream")
    await memory_service.create_or_update_memory(db_session, user_id=1, content="I like coding in Python")
    
    results = await memory_service.search_memories(db_session, user_id=1, query="chocolate")
    assert len(results) == 1
    assert "chocolate" in results[0].content

@pytest.mark.asyncio
async def test_cleanup_expired_memories(db_session):
    # 만료된 메모리
    m1 = await memory_service.create_or_update_memory(db_session, user_id=1, content="Expired", ttl_days=-1)
    # TTL을 음수로 줄 수 없으므로 직접 set
    m1.expires_at = utcnow() - timedelta(days=1)
    await db_session.commit()
    
    # 정상 메모리
    await memory_service.create_or_update_memory(db_session, user_id=1, content="Alive", ttl_days=1)
    
    # 클린업 전
    all_m = await memory_service.list_memories(db_session, user_id=1, include_expired=True)
    assert len(all_m) == 2
    
    # 클린업
    await memory_service.cleanup_expired_memories(db_session, user_id=1)
    
    # 클린업 후
    all_m_after = await memory_service.list_memories(db_session, user_id=1, include_expired=True)
    assert len(all_m_after) == 1
    assert all_m_after[0].content == "Alive"
