import unittest
from datetime import datetime as real_datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


from backend.services.alarm import llm_logic


@pytest.mark.integration
class TestAlarmRandomTopicFallback(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        from backend.services.llm.service import LLMService
        LLMService._instance = None

    async def test_random_topic_skips_when_not_10min(self) -> None:
        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "load_last_random_topic_sent_at", return_value=real_datetime(2025, 1, 1, 12, 10)),
        ):
            instance = MockLLM.get_instance.return_value
            instance.is_loaded.return_value = True
            mock_datetime.now.return_value = real_datetime(2025, 1, 1, 12, 12)

            result = await llm_logic.summarize_with_llm([])
            self.assertIsNone(result)

    async def test_random_topic_catches_up_when_missed_slot(self) -> None:
        anchored = "역사 이야기를 툭 던져요! 조선 시대 기록은 꽤 촘촘해서, 한 번 보면 오히려 숨이 턱 막힌다더라요. 아무튼 이런 얘기 꺼내면 괜히 고개가 끄덕끄덕!"

        save_category_mock = MagicMock()
        save_last_sent_mock = MagicMock()
        
        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "load_recent_categories", return_value=[]),
            patch.object(llm_logic, "save_recent_category", save_category_mock),
            patch.object(llm_logic, "load_last_random_topic_sent_at", return_value=real_datetime(2025, 1, 1, 12, 0)),
            patch.object(llm_logic, "save_last_random_topic_sent_at", save_last_sent_mock),
            patch.object(llm_logic.random, "choice", side_effect=lambda seq: "역사/문화" if "역사/문화" in seq else seq[0]),
            patch.object(llm_logic.random, "shuffle", return_value=None),
            patch.object(llm_logic, "generate_with_main_llm_async", new=AsyncMock(return_value=anchored)),
        ):
            instance = MockLLM.get_instance.return_value
            instance.is_loaded.return_value = True
            instance.reset_context.return_value = None
            mock_datetime.now.return_value = real_datetime(2025, 1, 1, 12, 15)

            result = await llm_logic.summarize_with_llm([])
            self.assertIsInstance(result, str)
            self.assertTrue(result)
            self.assertIn("역사", result)
            save_category_mock.assert_called_with("역사/문화")
            save_last_sent_mock.assert_called()

    async def test_random_topic_forwards_model_and_provider_kwargs(self) -> None:
        anchored = "역사 이야기를 툭 던져요! 조선 시대 기록은 꽤 촘촘해서, 한 번 보면 오히려 숨이 턱 막힌다더라요. 아무튼 이런 얘기 꺼내면 괜히 고개가 끄덕끄덕!"
        generate_mock = AsyncMock(return_value=anchored)

        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "load_recent_categories", return_value=[]),
            patch.object(llm_logic, "load_last_random_topic_sent_at", return_value=None),
            patch.object(llm_logic, "save_recent_category", MagicMock()),
            patch.object(llm_logic, "save_last_random_topic_sent_at", MagicMock()),
            patch.object(llm_logic.random, "choice", side_effect=lambda seq: "역사/문화" if "역사/문화" in seq else seq[0]),
            patch.object(llm_logic.random, "shuffle", return_value=None),
            patch.object(llm_logic, "generate_with_main_llm_async", new=generate_mock),
        ):
            instance = MockLLM.get_instance.return_value
            instance.is_loaded.return_value = True
            instance.reset_context.return_value = None
            mock_datetime.now.return_value = real_datetime(2025, 1, 1, 12, 10)

            await llm_logic.summarize_with_llm(
                [],
                model="openai/gpt-5.1-chat",
                api_key="openrouter-key",
                base_url="https://openrouter.ai/api/v1",
            )

            called_kwargs = generate_mock.await_args.kwargs
            self.assertEqual(called_kwargs.get("model"), "openai/gpt-5.1-chat")
            self.assertEqual(called_kwargs.get("api_key"), "openrouter-key")
            self.assertEqual(called_kwargs.get("base_url"), "https://openrouter.ai/api/v1")

    async def test_random_topic_skips_after_validation_failures(self) -> None:
        # 한국어 비율이 낮아 실패가 발생하도록 유도
        invalid = "Generating random... ERROR 500. #@!$!@#$ retry later..."

        save_mock = MagicMock()
        save_last_sent_mock = MagicMock()

        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "load_recent_categories", return_value=[]),
            patch.object(llm_logic, "save_recent_category", save_mock),
            patch.object(llm_logic, "save_last_random_topic_sent_at", save_last_sent_mock),
            patch.object(llm_logic.random, "choice", side_effect=lambda seq: "도시괴담/오컬트" if "도시괴담/오컬트" in seq else seq[0]),
            patch.object(llm_logic.random, "shuffle", return_value=None),
            patch.object(llm_logic, "generate_with_main_llm_async", new=AsyncMock(return_value=invalid)),
            patch.object(llm_logic, "refine_draft_with_light_llm_async", new=AsyncMock(return_value=invalid)),
        ):
            instance = MockLLM.get_instance.return_value
            instance.is_loaded.return_value = True
            instance.reset_context.return_value = None
            mock_datetime.now.return_value = real_datetime(2025, 1, 1, 12, 10)

            result = await llm_logic.summarize_with_llm([])
            self.assertIsInstance(result, str)
            self.assertIn("⚠️", result) # 에러 메시지 반환 확인
            self.assertIn("도시괴담/오컬트", result)
            self.assertIn("실패 사유", result)
