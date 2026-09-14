from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.alarm import llm_logic


@pytest.mark.asyncio
async def test_empty_list_returns_none_without_llm_call() -> None:
    llm = MagicMock()
    llm.is_loaded.return_value = False

    with patch.object(llm_logic.LLMService, "get_instance", return_value=llm):
        result = await llm_logic.summarize_with_llm([])

    assert result is None


@pytest.mark.asyncio
async def test_duplicate_notifications_are_deduplicated_before_llm_call() -> None:
    llm = MagicMock()
    llm.is_loaded.return_value = True
    generate = AsyncMock(return_value="- Testing: 중복 메시지")
    duplicate_item = {
        "text": "중복 메시지",
        "sender": "Testing",
        "app_title": "App",
    }

    with (
        patch.object(llm_logic.LLMService, "get_instance", return_value=llm),
        patch.object(llm_logic, "generate_with_main_llm_async", new=generate),
    ):
        result = await llm_logic.summarize_with_llm([duplicate_item, duplicate_item])

    assert result == "- Testing: 중복 메시지"
    messages = generate.await_args.args[0]
    assert messages[0]["content"].count("중복 메시지") == 1
