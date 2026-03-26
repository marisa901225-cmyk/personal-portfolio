import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.alarm import processor


class TestAlarmProcessorLlmRouting(unittest.IsolatedAsyncioTestCase):
    async def test_summary_route_uses_summary_llm_endpoint(self):
        alarm = SimpleNamespace(
            id=1,
            raw_text="[KB] 카드 승인 12,000원",
            masked_text=None,
            sender="KB카드",
            app_name="KB",
            package="com.kb.app",
            app_title="결제 알림",
            conversation=None,
            status="pending",
            classification=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [alarm]

        env = {
            "ALARM_SUMMARY_LLM_BASE_URL": "http://openvino-server:8082",
            "ALARM_SUMMARY_MODEL_OVERRIDE": "summary-model",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(processor, "check_upcoming_matches", new=AsyncMock()),
            patch.object(processor, "_get_nb_pipeline", return_value=None),
            patch("backend.services.users.get_or_create_single_user", return_value=MagicMock(id=1)),
            patch.object(processor, "is_whitelisted", return_value=False),
            patch.object(processor, "is_review_spam", return_value=False),
            patch.object(processor, "is_spam", return_value=(False, "")),
            patch.object(processor, "is_promo_spam", return_value=False),
            patch.object(processor, "is_spam_llm", return_value=(False, "llm_ham")) as mock_is_spam_llm,
            patch.object(processor, "parse_card_approval", return_value=None),
            patch.object(processor, "summarize_with_llm", new=AsyncMock(return_value="중요 알림 요약")) as mock_summary,
            patch.object(processor, "generate_random_message_payload", new=AsyncMock()) as mock_random,
            patch.object(processor, "send_telegram_message", new=AsyncMock()),
        ):
            await processor.process_pending_alarms(db, model_override="shared-model")

        self.assertEqual(mock_is_spam_llm.call_args.kwargs["model"], "summary-model")
        self.assertEqual(
            mock_is_spam_llm.call_args.kwargs["base_url_override"],
            "http://openvino-server:8082",
        )
        self.assertEqual(mock_summary.await_args.kwargs["model"], "summary-model")
        self.assertEqual(
            mock_summary.await_args.kwargs["base_url_override"],
            "http://openvino-server:8082",
        )
        mock_random.assert_not_awaited()

    async def test_random_route_uses_random_llm_endpoint(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        env = {
            "ALARM_RANDOM_LLM_BASE_URL": "http://llama-server-vulkan-huihui:8083",
            "ALARM_RANDOM_MODEL_OVERRIDE": "random-model",
        }

        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(processor, "check_upcoming_matches", new=AsyncMock()),
            patch.object(processor, "_get_nb_pipeline", return_value=None),
            patch("backend.services.users.get_or_create_single_user", return_value=MagicMock(id=1)),
            patch.object(
                processor,
                "generate_random_message_payload",
                new=AsyncMock(return_value={"title": "랜덤 제목", "body": "랜덤 본문"}),
            ) as mock_random,
            patch.object(processor, "summarize_with_llm", new=AsyncMock()) as mock_summary,
            patch.object(processor, "send_telegram_message", new=AsyncMock()),
        ):
            await processor.process_pending_alarms(db, model_override="shared-model")

        self.assertEqual(mock_random.await_args.kwargs["model"], "random-model")
        self.assertEqual(
            mock_random.await_args.kwargs["base_url_override"],
            "http://llama-server-vulkan-huihui:8083",
        )
        mock_summary.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
