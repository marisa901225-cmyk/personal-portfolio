import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.alarm import processor


class TestAlarmProcessorNoRandomWithExpense(unittest.IsolatedAsyncioTestCase):
    async def test_expense_only_batch_does_not_trigger_random_topic(self):
        alarm = SimpleNamespace(
            id=1,
            raw_text="우리카드 승인 12,000원 테스트상점",
            masked_text=None,
            sender="우리카드",
            app_name="카드앱",
            package="com.card.app",
            app_title="결제 알림",
            conversation=None,
            status="pending",
            classification=None,
            received_at=datetime.now(timezone.utc),
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [alarm]

        fake_user = SimpleNamespace(id=123)
        fake_card_info = {
            "date": datetime.now(timezone.utc),
            "amount": -12000,
            "merchant": "테스트상점",
            "method": "카드",
        }

        with patch.object(processor, "check_upcoming_matches", new=AsyncMock()), \
             patch.object(processor, "_get_nb_pipeline", return_value=None), \
             patch("backend.services.users.get_or_create_single_user", return_value=fake_user), \
             patch.object(processor, "should_ignore", return_value=False), \
             patch.object(processor, "is_whitelisted", return_value=True), \
             patch.object(processor, "parse_card_approval", return_value=fake_card_info), \
             patch.object(processor, "summarize_expenses_with_llm", new=AsyncMock(return_value="지출이 안정적이에요.")), \
             patch.object(processor, "summarize_with_llm", new=AsyncMock(return_value="랜덤메시지")), \
             patch.object(processor, "send_telegram_message", new=AsyncMock()) as mock_send:

            await processor.process_pending_alarms(db)

            processor.summarize_with_llm.assert_not_awaited()
            processor.summarize_expenses_with_llm.assert_awaited_once()
            mock_send.assert_awaited_once()

            sent_text = mock_send.await_args.args[0]
            self.assertIn("[가계부 리포트]", sent_text)
            self.assertNotIn("랜덤메시지", sent_text)


if __name__ == "__main__":
    unittest.main()
