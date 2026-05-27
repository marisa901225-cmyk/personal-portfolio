import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.routers.ai_chat import AiChatMessageRequest, create_ai_chat_message
from backend.core.db import Base
from backend.routers.ai_memos import (
    AiMemoCreate,
    AiMemoUpdate,
    create_ai_memo,
    delete_ai_memo,
    list_ai_memos,
    update_ai_memo,
)


class _FakeLLM:
    def __init__(self, answer: str = "정리된 메모") -> None:
        self.answer = answer
        self.called_messages = None

    def generate_chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.called_messages = messages
        return self.answer

    def get_last_error(self) -> str | None:
        return None

    def last_route(self) -> str:
        return "remote"

    def last_used_paid(self) -> bool:
        return False


def _create_memo_session():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = Path(tmpdir.name) / "ai_memos_test.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return tmpdir, engine, session_local()


def test_ai_memo_crud_flow() -> None:
    tmpdir, engine, db = _create_memo_session()
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
    tmpdir, engine, db = _create_memo_session()
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


@pytest.mark.asyncio
async def test_create_ai_chat_message_uses_memo_context(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeLLM()
    monkeypatch.setattr("backend.routers.ai_chat.LLMService.get_instance", lambda: fake)

    response = await create_ai_chat_message(
        AiChatMessageRequest(
            memo="해야 할 일: 장보기",
            instruction="짧게 정리해줘",
            mode="memo",
        )
    )

    assert response.answer == "정리된 메모"
    assert response.route == "remote"
    assert response.used_paid is False
    assert fake.called_messages is not None
    assert "해야 할 일: 장보기" in fake.called_messages[1]["content"]
    assert "짧게 정리해줘" in fake.called_messages[1]["content"]


def test_build_messages_preserves_raw_memo_tokens() -> None:
    from backend.routers.ai_chat import _build_messages

    messages = _build_messages(
        AiChatMessageRequest(
            memo="LPH-1 메모장 대용 mg -50 1 mg -32 7 Elb 8",
            instruction="정리해줘",
            mode="memo",
        )
    )

    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "LPH-1 메모장 대용" in system_prompt
    assert "항목 3개" in system_prompt
    assert "| mg -50 | 1 |" in system_prompt
    assert "| mg -32 | 7 |" in system_prompt
    assert "| Elb | 8 |" in system_prompt
    assert "<reason>" in system_prompt
    assert "mg -50" in user_prompt
    assert "1 mg -32" in user_prompt
    assert "7 Elb 8" in user_prompt


def test_build_messages_includes_shortcut_translation_example() -> None:
    from backend.routers.ai_chat import _build_messages

    messages = _build_messages(
        AiChatMessageRequest(
            memo="win+페이지 업,다운\n캡스+w 챗지피티",
            instruction="영어 단축키 표로 정리해줘",
            mode="memo",
        )
    )

    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "| Win + Page Up | 이전 페이지 |" in system_prompt
    assert "| Win + Page Down | 다음 페이지 |" in system_prompt
    assert "| Win + C | 확인 필요 |" in system_prompt
    assert "| Caps + W | ChatGPT |" in system_prompt
    assert "페이지 업" in user_prompt
    assert "캡스+w 챗지피티" in user_prompt
