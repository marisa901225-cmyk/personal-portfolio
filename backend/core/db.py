from __future__ import annotations

import os
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

BASE_DIR = Path(__file__).resolve().parents[1]
DB_DIR = BASE_DIR / "storage" / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)


from .config import settings

DATABASE_URL = settings.database_url

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # SQLite 특성상 동일 스레드 제한을 끄고 사용 (check_same_thread=False)
    # ⚠️ 주의: 멀티스레드 환경에서 세션 관리를 신중히 해야 함 (도라의 경고! 💖)
    # timeout: DB 잠겨있을 때 대기 시간 (30초로 상향하여 busy 에러 방지)
    connect_args = {"check_same_thread": False, "timeout": 30}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[override]
    """SQLite 사용 시 성능 및 동시성 최적화를 위한 PRAGMA 설정"""
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL 모드: 읽기와 쓰기 동시성 향상
        cursor.execute("PRAGMA journal_mode=WAL")
        # synchronous=NORMAL: WAL 모드에서 성능과 안정성의 최적 밸런스 (도라 추천 💖)
        cursor.execute("PRAGMA synchronous=NORMAL")
        # cache_size: 약 2MB의 메모리 캐시 할당
        cursor.execute("PRAGMA cache_size=-2000")
        cursor.close()
    except Exception:
        # PRAGMA 설정 실패해도 동작에는 치명적이지 않으므로 로그만 남김
        pass


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
