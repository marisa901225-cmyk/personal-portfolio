import os
import unittest
from datetime import datetime as real_datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite:////home/dlckdgn/personal-portfolio/devplan/test_db/test.db")
os.environ.setdefault("API_TOKEN", "test-token")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from backend.services.alarm import llm_logic


class TestRandomMessageScriptFilter(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        from backend.services.llm.service import LLMService
        LLMService._instance = None

    async def test_random_message_refines_non_korean_cjk_chars(self) -> None:
        invalid = (
            "그 흔적은 교장 선생님의 외套에 스며들어, 낡은 리ール에서 튀어나온 장면처럼 이어졌다. "
            "아무도 눈치채지 못한 기호가 문장 사이를 미끄러졌고, 듣는 사람은 의미보다 분위기에 먼저 휩쓸렸다. "
            "그래서 말끝이 자꾸 낯선 방향으로 새는 밤이었다."
        )
        refined = (
            "역사 이야기를 꺼내면 늘 반전이 있어. 기록 한 줄이 오늘의 선택을 바꾸기도 하니까, "
            "오늘은 작은 습관 하나를 남겨서 내일의 근거를 만들어 보자. "
            "결국 역사는 멀리 있지 않고 하루의 반복에서 시작된다."
        )

        save_category_mock = MagicMock()
        save_last_sent_mock = MagicMock()

        with (
            patch.object(llm_logic, "LLMService") as MockLLM,
            patch.object(llm_logic, "datetime") as mock_datetime,
            patch.object(llm_logic, "load_recent_categories", return_value=[]),
            patch.object(llm_logic, "save_recent_category", save_category_mock),
            patch.object(llm_logic, "load_last_random_topic_sent_at", return_value=None),
            patch.object(llm_logic, "save_last_random_topic_sent_at", save_last_sent_mock),
            patch.object(llm_logic.random, "choice", side_effect=lambda seq: "역사/문화" if "역사/문화" in seq else seq[0]),
            patch.object(llm_logic.random, "shuffle", return_value=None),
            patch.object(llm_logic, "generate_with_main_llm_async", new=AsyncMock(return_value=invalid)),
            patch.object(llm_logic, "refine_draft_with_light_llm_async", new=AsyncMock(return_value=refined)),
        ):
            instance = MockLLM.get_instance.return_value
            instance.is_loaded.return_value = True
            instance.reset_context.return_value = None
            mock_datetime.now.return_value = real_datetime(2025, 1, 2, 12, 10)

            result = await llm_logic.summarize_with_llm([])

        self.assertIsInstance(result, str)
        self.assertIn("역사", result)
        self.assertNotIn("外", result)
        self.assertNotIn("リ", result)
        self.assertTrue(save_category_mock.called)
        save_last_sent_mock.assert_called()
