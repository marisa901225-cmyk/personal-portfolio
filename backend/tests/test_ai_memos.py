import tempfile
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.db import Base
from backend.routers.ai_memos import (
    AiMemoCreate,
    AiMemoUpdate,
    create_ai_memo,
    delete_ai_memo,
    list_ai_memos,
    update_ai_memo,
)


def _create_session():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = Path(tmpdir.name) / "ai_memos_test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmpdir, engine, session_local()


def test_ai_memo_crud_flow() -> None:
    tmpdir, engine, db = _create_session()
    try:
        first = create_ai_memo(
            AiMemoCreate(title="단축키", content="win+page up\ncaps+w ChatGPT"),
            db,
        )
        second = create_ai_memo(
            AiMemoCreate(title="LPH-1", content="mg -50 1\nmg -32 7"),
            db,
        )

        memos = list_ai_memos(db)
        assert [memo.id for memo in memos] == [second.id, first.id]

        updated = update_ai_memo(
            first.id,
            AiMemoUpdate(title="단축키 정리", content="| 항목 | 값 |\n| --- | --: |\n| win+c | 1 |"),
            db,
        )
        assert updated.title == "단축키 정리"
        assert "| 항목 | 값 |" in updated.content

        delete_ai_memo(second.id, db)
        remaining = list_ai_memos(db)
        assert [memo.id for memo in remaining] == [first.id]
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()


def test_ai_memo_delete_rejects_other_ids() -> None:
    tmpdir, engine, db = _create_session()
    try:
        create_ai_memo(AiMemoCreate(title="테스트", content="내용"), db)
        try:
            delete_ai_memo(9999, db)
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("delete_ai_memo should reject missing memo ids")
    finally:
        db.close()
        engine.dispose()
        tmpdir.cleanup()
