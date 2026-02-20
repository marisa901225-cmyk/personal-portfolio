import pytest
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.models import Base, User
from backend.services import memory_service
from backend.core.time_utils import utcnow

# 테스트용 인메모리 SQLite (동기)
TEST_DATABASE_URL = "sqlite://"


@pytest.fixture(scope="function")
def db_session():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    # 기본 사용자 생성
    user = User(id=1, name="Test User")
    session.add(user)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_create_memory_success(db_session):
    content = "Annabeth is my beautiful girlfriend"
    category = "profile"

    memory = memory_service.create_or_update_memory(
        db_session, user_id=1, content=content, category=category, importance=5
    )

    assert memory.id is not None
    assert memory.content == content
    assert memory.category == category
    assert memory.importance == 5


def test_create_or_update_with_key(db_session):
    key = "daily_routine"
    memory_service.create_or_update_memory(
        db_session, user_id=1, content="Wake up at 7am", key=key
    )

    # 동일 키로 업데이트
    updated = memory_service.create_or_update_memory(
        db_session, user_id=1, content="Wake up at 8am", key=key
    )

    assert updated.content == "Wake up at 8am"

    # 전체 개수 확인 (1개여야 함)
    memories = memory_service.list_memories(db_session, user_id=1)
    assert len(memories) == 1


def test_list_memories_filtering(db_session):
    memory_service.create_or_update_memory(db_session, user_id=1, content="Info 1", category="fact", importance=3)
    memory_service.create_or_update_memory(db_session, user_id=1, content="Info 2", category="profile", importance=1)

    # 중요도 필터링
    m_imp3 = memory_service.list_memories(db_session, user_id=1, min_importance=3)
    assert len(m_imp3) == 1
    assert m_imp3[0].content == "Info 1"

    # 카테고리 필터링
    m_profile = memory_service.list_memories(db_session, user_id=1, category="profile")
    assert len(m_profile) == 1
    assert m_profile[0].content == "Info 2"


def test_search_memories(db_session):
    memory_service.create_or_update_memory(db_session, user_id=1, content="I like chocolate ice cream")
    memory_service.create_or_update_memory(db_session, user_id=1, content="I like coding in Python")

    results = memory_service.search_memories(db_session, user_id=1, query="chocolate")
    assert len(results) == 1
    assert "chocolate" in results[0].content


def test_cleanup_expired_memories(db_session):
    # 만료된 메모리
    m1 = memory_service.create_or_update_memory(db_session, user_id=1, content="Expired", ttl_days=0)
    # TTL을 음수로 줄 수 없으므로 직접 set
    m1.expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    # 정상 메모리
    memory_service.create_or_update_memory(db_session, user_id=1, content="Alive", ttl_days=1)

    # 클린업 전
    all_m = memory_service.list_memories(db_session, user_id=1, include_expired=True)
    assert len(all_m) == 2

    # 클린업
    memory_service.cleanup_expired_memories(db_session, user_id=1)

    # 클린업 후
    all_m_after = memory_service.list_memories(db_session, user_id=1, include_expired=True)
    assert len(all_m_after) == 1
    assert all_m_after[0].content == "Alive"
