import pytest

from backend.routers.ai_chat import AiChatMessageRequest, create_ai_chat_message


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
    assert "mg: -50" in system_prompt
    assert "1 mg: -32" in system_prompt
    assert "7 Elb: 8" in system_prompt
    assert "<reason>" in system_prompt
    assert "mg -50" in user_prompt
    assert "1 mg -32" in user_prompt
    assert "7 Elb 8" in user_prompt
