import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from backend.main import app
from backend.core.db import get_db
from backend.core.models import Base, User
import os

# 테스트용 DB
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="function")
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session() as session:
        # 기본 사용자
        user = User(id=1, name="Test User")
        session.add(user)
        await session.commit()
        yield session
    await engine.dispose()

@pytest.fixture(scope="function")
def client(db_session):
    # get_db 의존성 오버라이드
    async def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_create_memory_api(client):
    # API 토큰 설정
    headers = {"X-API-Token": "test-token"}
    
    response = client.post(
        "/api/memories/",
        json={
            "content": "Annabeth loves me",
            "category": "profile",
            "importance": 5
        },
        headers=headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["content"] == "Annabeth loves me"
    assert data["importance"] == 5

@pytest.mark.asyncio
async def test_get_memories_list_api(client):
    headers = {"X-API-Token": "test-token"}
    # 미리 데이터 생성
    client.post("/api/memories/", json={"content": "Memory 1", "category": "fact"}, headers=headers)
    
    response = client.get("/api/memories/", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) >= 1

@pytest.mark.asyncio
async def test_search_memories_api(client):
    headers = {"X-API-Token": "test-token"}
    client.post("/api/memories/", json={"content": "I love spicy food", "key": "food_pref"}, headers=headers)
    
    response = client.post(
        "/api/memories/search",
        json={"query": "spicy"},
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert "spicy" in data[0]["content"]

@pytest.mark.asyncio
async def test_get_memory_not_found(client):
    headers = {"X-API-Token": "test-token"}
    response = client.get("/api/memories/9999", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Memory not found"

@pytest.mark.asyncio
async def test_delete_memory_api(client):
    headers = {"X-API-Token": "test-token"}
    # 생성
    res = client.post("/api/memories/", json={"content": "To be deleted"}, headers=headers)
    memory_id = res.json()["id"]
    
    # 삭제
    del_res = client.delete(f"/api/memories/{memory_id}", headers=headers)
    assert del_res.status_code == 204
    
    # 확인
    get_res = client.get(f"/api/memories/{memory_id}", headers=headers)
    assert get_res.status_code == 404
