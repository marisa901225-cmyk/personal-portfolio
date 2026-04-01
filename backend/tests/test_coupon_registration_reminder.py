import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.scripts.runners import run_sync_prices_scheduler as scheduler_runner


class TestCouponRegistrationReminder(unittest.IsolatedAsyncioTestCase):
    async def test_sends_monthly_coupon_reminder_via_main_bot(self):
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = None
        mock_context.__aexit__.return_value = None

        with (
            patch.object(scheduler_runner, "SessionLocal", return_value=MagicMock()) as mock_session_local,
            patch.object(scheduler_runner, "monitor_job_async", return_value=mock_context),
            patch.object(scheduler_runner, "send_telegram_message", new=AsyncMock(return_value=True)) as mock_send,
        ):
            await scheduler_runner.run_coupon_registration_reminder()

        mock_session = mock_session_local.return_value
        mock_send.assert_awaited_once()
        sent_text = mock_send.await_args.args[0]
        self.assertIn("쿠폰 등록", sent_text)
        self.assertEqual(mock_send.await_args.kwargs["bot_type"], "main")
        mock_session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
