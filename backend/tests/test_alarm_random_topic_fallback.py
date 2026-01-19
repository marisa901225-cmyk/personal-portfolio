import unittest
from datetime import datetime as real_datetime
from unittest.mock import AsyncMock, MagicMock, patch


from backend.services.alarm import llm_logic


class TestAlarmRandomTopicFallback(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        from backend.services.llm.service import LLMService
        LLMService._instance = None

    async def test_random_topic_skips_when_not_10min(self) -> None:
        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "_load_last_random_topic_sent_at", return_value=real_datetime(2025, 1, 1, 12, 10)),
        ):
            instance = MockLLM.get_instance.return_value
            instance.is_loaded.return_value = True
            mock_datetime.now.return_value = real_datetime(2025, 1, 1, 12, 12)

            result = await llm_logic.summarize_with_llm([])
            self.assertIsNone(result)

    async def test_random_topic_catches_up_when_missed_slot(self) -> None:
        def choice_side_effect(seq):
            if isinstance(seq, (list, tuple)) and "역사/문화" in seq:
                return "역사/문화"
            return seq[0]

        anchored = "역사 이야기를 툭 던져요! 조선 시대 기록은 꽤 촘촘해서, 한 번 보면 오히려 숨이 턱 막힌다더라요. 아무튼 이런 얘기 꺼내면 괜히 고개가 끄덕끄덕!"

        save_category_mock = MagicMock()
        save_last_sent_mock = MagicMock()

        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "_load_recent_categories", return_value=[]),
            patch.object(llm_logic, "_save_recent_category", save_category_mock),
            patch.object(llm_logic, "_load_last_random_topic_sent_at", return_value=real_datetime(2025, 1, 1, 12, 0)),
            patch.object(llm_logic, "_save_last_random_topic_sent_at", save_last_sent_mock),
            patch.object(llm_logic.random, "choice", side_effect=choice_side_effect),
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

    async def test_random_topic_falls_back_after_validation_failures(self) -> None:
        def choice_side_effect(seq):
            if isinstance(seq, (list, tuple)) and "역사/문화" in seq:
                return "역사/문화"
            return seq[0]

        invalid = (
            "질문 하나 툭 던져볼까요? "
            "요즘은 어째서 그런지 사소한 것들이 더 눈에 들어오더라요, 이상하죠. "
            "아무튼 오늘은 그냥 이런 기분입니다, 하하. "
            "가볍게 웃고 지나가도 되는 얘기라서 더 마음이 편하달까요, 으흠!"
        )

        save_mock = MagicMock()
        save_last_sent_mock = MagicMock()

        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "_load_recent_categories", return_value=[]),
            patch.object(llm_logic, "_save_recent_category", save_mock),
            patch.object(llm_logic, "_save_last_random_topic_sent_at", save_last_sent_mock),
            patch.object(llm_logic.random, "choice", side_effect=choice_side_effect),
            patch.object(llm_logic, "generate_with_main_llm_async", new=AsyncMock(return_value=invalid)),
            patch.object(llm_logic, "refine_draft_with_light_llm_async", new=AsyncMock(return_value=invalid)),
        ):
            instance = MockLLM.get_instance.return_value
            instance.is_loaded.return_value = True
            instance.reset_context.return_value = None
            mock_datetime.now.return_value = real_datetime(2025, 1, 1, 12, 10)

            result = await llm_logic.summarize_with_llm([])
            self.assertIsInstance(result, str)
            self.assertTrue(result)
            self.assertIn("역사/문화", result)
            save_mock.assert_called_with("역사/문화")
            save_last_sent_mock.assert_called()
