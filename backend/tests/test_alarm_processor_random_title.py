import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.alarm import processor


class TestAlarmProcessorRandomTitle(unittest.IsolatedAsyncioTestCase):
    async def test_random_payload_title_is_used_in_header(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with (
            patch.object(processor, "check_upcoming_matches", new=AsyncMock()),
            patch.object(processor, "_get_nb_pipeline", return_value=None),
            patch("backend.services.users.get_or_create_single_user", return_value=MagicMock(id=1)),
            patch.object(
                processor,
                "generate_random_message_payload",
                new=AsyncMock(return_value={"title": "폴라로이드 핫픽스", "body": "본문 테스트"}),
            ),
            patch.object(processor, "summarize_with_llm", new=AsyncMock()) as mock_summary,
            patch.object(processor, "send_telegram_message", new=AsyncMock()) as mock_send,
        ):
            await processor.process_pending_alarms(db)

        mock_summary.assert_not_awaited()
        mock_send.assert_awaited_once()
        sent_text = mock_send.await_args.args[0]
        self.assertIn("[폴라로이드 핫픽스]", sent_text)
        self.assertIn("본문 테스트", sent_text)


if __name__ == "__main__":
    unittest.main()
