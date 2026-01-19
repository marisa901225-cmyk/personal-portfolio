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
    # SQLite 특성상 동일 스레드 제한을 끄고 사용
    # timeout: DB 잠겨있을 때 대기 시간 (초) - 기본값보다 넉넉하게 설정하여 busy 에러 방지
    connect_args = {"check_same_thread": False, "timeout": 15}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True,
)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:  # type: ignore[override]
    # SQLite 사용 시 권장 PRAGMA 설정
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
    except Exception:
        # PRAGMA 설정 실패해도 애플리케이션 동작에는 치명적이지 않으므로 무시
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
