import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_temp_dir.name}/test.db")
os.environ.setdefault("API_TOKEN", "test-token")


from backend.routers.handlers.query_handler import _handle_esports  # noqa: E402


class EsportsScheduleNoHallucinationTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_schedule_short_circuits_without_llm(self) -> None:
        with patch(
            "backend.services.news_collector.NewsCollector.refine_schedules_with_duckdb",
            return_value="검색된 관련 일정이 없습니다.",
        ), patch(
            "backend.services.llm_service.LLMService.get_instance",
            new=MagicMock(),
        ) as mock_llm_get_instance, patch(
            "backend.routers.handlers.query_handler.send_telegram_message",
            new=AsyncMock(),
        ) as mock_send:
            await _handle_esports("오늘 LCK 일정 알려줘")

            mock_llm_get_instance.assert_not_called()
            self.assertTrue(mock_send.called)
            sent_text = mock_send.call_args[0][0]
            self.assertIn("일정이 없습니다", sent_text)
            self.assertNotIn("다음 주", sent_text)
            self.assertNotIn("공식", sent_text)

    async def test_with_schedule_uses_llm(self) -> None:
        stub_llm = MagicMock()
        stub_llm.generate_chat.return_value = "01/16 17:00 T1 vs Gen.G"

        with patch(
            "backend.services.news_collector.NewsCollector.refine_schedules_with_duckdb",
            return_value="🗓️ 01/16 17:00 | [LoL] T1 vs Gen.G\n   🔗 https://example.com",
        ), patch(
            "backend.routers.handlers.query_handler.load_prompt",
            return_value="(test prompt)",
        ), patch(
            "backend.services.llm_service.LLMService.get_instance",
            return_value=stub_llm,
        ) as mock_llm_get_instance, patch(
            "backend.routers.handlers.query_handler.send_telegram_message",
            new=AsyncMock(),
        ) as mock_send:
            await _handle_esports("오늘 LCK 일정 알려줘")

            mock_llm_get_instance.assert_called_once()
            stub_llm.generate_chat.assert_called_once()
            sent_text = mock_send.call_args[0][0]
            self.assertIn("T1 vs Gen.G", sent_text)
