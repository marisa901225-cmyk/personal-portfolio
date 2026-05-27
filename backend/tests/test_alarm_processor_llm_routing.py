import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.alarm import processor
from backend.services.alarm.alarm_summary_service import (
    ALARM_SUMMARY_DEFAULT_MAX_TOKENS,
    _AlarmSummaryDeps,
    _generate_alarm_summary_async,
)
from backend.services.alarm.filters import is_review_spam, is_whitelisted
from backend.services.llm.service import LLMService as CoreLLMService


class TestAlarmProcessorLlmRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.weekend_patcher = patch.object(processor, "_is_weekend", return_value=False)
        self.mock_is_weekend = self.weekend_patcher.start()

    def tearDown(self):
        self.weekend_patcher.stop()
        CoreLLMService._instance = None

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

    async def test_random_route_does_not_inherit_summary_openrouter_kwargs(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        with (
            patch.dict(
                os.environ,
                {
                    "ALARM_RANDOM_LLM_BASE_URL": "",
                    "ALARM_RANDOM_MODEL_OVERRIDE": "",
                },
                clear=False,
            ),
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
            await processor.process_pending_alarms(
                db,
                model_override="openai/gpt-5.1-chat",
                api_key="openrouter-key",
                base_url="https://openrouter.ai/api/v1",
            )

        self.assertIsNone(mock_random.await_args.kwargs["model"])
        self.assertNotIn("api_key", mock_random.await_args.kwargs)
        self.assertNotIn("base_url", mock_random.await_args.kwargs)
        self.assertNotIn("base_url_override", mock_random.await_args.kwargs)
        mock_summary.assert_not_awaited()

    async def test_weekend_summary_route_forces_paid_backend(self):
        self.mock_is_weekend.return_value = True
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
            "ALARM_SUMMARY_MODEL_OVERRIDE": "summary-local-model",
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
            patch.object(processor, "generate_random_message_payload", new=AsyncMock()),
            patch.object(processor, "send_telegram_message", new=AsyncMock()),
        ):
            await processor.process_pending_alarms(db, model_override="paid-model")

        self.assertEqual(mock_is_spam_llm.call_args.kwargs["model"], "paid-model")
        self.assertTrue(mock_is_spam_llm.call_args.kwargs["force_paid_only"])
        self.assertNotIn("base_url_override", mock_is_spam_llm.call_args.kwargs)
        self.assertEqual(mock_summary.await_args.kwargs["model"], "paid-model")
        self.assertTrue(mock_summary.await_args.kwargs["force_paid_only"])
        self.assertNotIn("base_url_override", mock_summary.await_args.kwargs)

    async def test_weekend_random_route_forces_paid_backend(self):
        self.mock_is_weekend.return_value = True
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        env = {
            "ALARM_RANDOM_LLM_BASE_URL": "http://llama-server-vulkan-huihui:8083",
            "ALARM_RANDOM_MODEL_OVERRIDE": "random-local-model",
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
            patch.object(processor, "summarize_with_llm", new=AsyncMock()),
            patch.object(processor, "send_telegram_message", new=AsyncMock()),
        ):
            await processor.process_pending_alarms(db, model_override="paid-model")

        self.assertEqual(mock_random.await_args.kwargs["model"], "paid-model")
        self.assertTrue(mock_random.await_args.kwargs["force_paid_only"])
        self.assertNotIn("base_url_override", mock_random.await_args.kwargs)

    async def test_filtered_promo_alarm_is_closed_without_summary(self):
        alarm = SimpleNamespace(
            id=1,
            raw_text="₩ 303 상당 코인 20개가 기다리고 있어요!",
            masked_text=None,
            sender="AliExpress",
            app_name="AliExpress",
            package="com.alibaba.aliexpresshd",
            app_title="₩ 303 상당 코인 20개가 기다리고 있어요!",
            conversation=None,
            status="pending",
            classification=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [alarm]

        with (
            patch.object(processor, "check_upcoming_matches", new=AsyncMock()),
            patch.object(processor, "_get_nb_pipeline", return_value=None),
            patch("backend.services.users.get_or_create_single_user", return_value=MagicMock(id=1)),
            patch.object(processor, "should_ignore", return_value=False),
            patch.object(processor, "is_whitelisted", return_value=False),
            patch.object(processor, "is_review_spam", return_value=True),
            patch.object(processor, "summarize_with_llm", new=AsyncMock()) as mock_summary,
            patch.object(
                processor,
                "generate_random_message_payload",
                new=AsyncMock(return_value={"title": "랜덤 제목", "body": "랜덤 본문"}),
            ) as mock_random,
            patch.object(processor, "send_telegram_message", new=AsyncMock()) as mock_send,
        ):
            await processor.process_pending_alarms(db)

        self.assertEqual(alarm.status, "processed")
        self.assertEqual(alarm.classification, "review_spam")
        mock_summary.assert_not_awaited()
        mock_random.assert_awaited_once()
        mock_send.assert_awaited_once()

    async def test_paid_prefix_notice_is_prepended_to_first_summary_message(self):
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

        fake_llm = MagicMock()
        fake_llm.last_used_paid.return_value = True
        fake_llm.telegram_paid_prefix.return_value = "NOTICE\n💰 "
        CoreLLMService._instance = fake_llm

        with (
            patch.object(processor, "check_upcoming_matches", new=AsyncMock()),
            patch.object(processor, "_get_nb_pipeline", return_value=None),
            patch("backend.services.users.get_or_create_single_user", return_value=MagicMock(id=1)),
            patch.object(processor, "is_whitelisted", return_value=False),
            patch.object(processor, "is_review_spam", return_value=False),
            patch.object(processor, "is_spam", return_value=(False, "")),
            patch.object(processor, "is_promo_spam", return_value=False),
            patch.object(processor, "is_spam_llm", return_value=(False, "llm_ham")),
            patch.object(processor, "parse_card_approval", return_value=None),
            patch.object(processor, "summarize_with_llm", new=AsyncMock(return_value="중요 알림 요약")),
            patch.object(processor, "generate_random_message_payload", new=AsyncMock()),
            patch.object(processor, "send_telegram_message", new=AsyncMock()) as mock_send,
        ):
            await processor.process_pending_alarms(db, model_override="shared-model")

        sent_text = mock_send.await_args.args[0]
        self.assertTrue(sent_text.startswith("NOTICE\n💰 "))

    async def test_spam_llm_receives_app_context_for_webnovel_notifications(self):
        alarm = SimpleNamespace(
            id=1,
            raw_text="흰토끼노데 전역했더니 재벌가에 결혼당함 - 미래를 생각해보죠...",
            masked_text=None,
            sender="흰토끼노데",
            app_name="문피아",
            package="com.munpia.app",
            app_title="신작 알림",
            conversation=None,
            status="pending",
            classification=None,
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [alarm]

        with (
            patch.object(processor, "check_upcoming_matches", new=AsyncMock()),
            patch.object(processor, "_get_nb_pipeline", return_value=None),
            patch("backend.services.users.get_or_create_single_user", return_value=MagicMock(id=1)),
            patch.object(processor, "is_whitelisted", return_value=False),
            patch.object(processor, "is_review_spam", return_value=False),
            patch.object(processor, "is_spam", return_value=(False, "")),
            patch.object(processor, "is_promo_spam", return_value=False),
            patch.object(processor, "is_spam_llm", return_value=(False, "llm_ham")) as mock_is_spam_llm,
            patch.object(processor, "parse_card_approval", return_value=None),
            patch.object(processor, "summarize_with_llm", new=AsyncMock(return_value="중요 알림 요약")),
            patch.object(processor, "generate_random_message_payload", new=AsyncMock()),
            patch.object(processor, "send_telegram_message", new=AsyncMock()),
        ):
            await processor.process_pending_alarms(db)

        spam_input = mock_is_spam_llm.call_args.args[0]
        self.assertIn("[app:문피아]", spam_input)
        self.assertIn("[pkg:com.munpia.app]", spam_input)
        self.assertIn("흰토끼노데", spam_input)

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

        with (
            patch.object(processor, "check_upcoming_matches", new=AsyncMock()),
            patch.object(processor, "_get_nb_pipeline", return_value=None),
            patch("backend.services.users.get_or_create_single_user", return_value=fake_user),
            patch.object(processor, "should_ignore", return_value=False),
            patch.object(processor, "is_whitelisted", return_value=True),
            patch.object(processor, "parse_card_approval", return_value=fake_card_info),
            patch.object(processor, "summarize_with_llm", new=AsyncMock(return_value="랜덤메시지")) as mock_summary,
            patch.object(processor, "generate_random_message_payload", new=AsyncMock(return_value=None)) as mock_random,
            patch.object(processor, "send_telegram_message", new=AsyncMock()) as mock_send,
        ):
            await processor.process_pending_alarms(db)

        mock_summary.assert_not_awaited()
        mock_random.assert_awaited_once()
        mock_send.assert_not_awaited()


class TestAlarmProcessorMailBatch(unittest.TestCase):
    def test_collapse_mail_batch_notifications_keeps_latest_per_app(self) -> None:
        items = [
            {"app_name": "Gmail", "sender": "새 메일 2개", "db_obj": SimpleNamespace(id=1)},
            {"app_name": "Gmail", "sender": "새 메일 3개", "db_obj": SimpleNamespace(id=2)},
            {"app_name": "카카오톡", "sender": "철수", "db_obj": SimpleNamespace(id=3)},
            {"app_name": "Gmail", "sender": "새 메일 5개", "db_obj": SimpleNamespace(id=4)},
        ]

        kept, dropped = processor._collapse_mail_batch_notifications(items)

        self.assertEqual([int(i["db_obj"].id) for i in kept], [3, 4])
        self.assertEqual([int(i["db_obj"].id) for i in dropped], [1, 2])


class AlarmFilterTests(unittest.TestCase):
    def test_aliexpress_coin_promo_is_not_delivery_whitelisted(self):
        text = "[AliExpress] ₩ 303 상당 코인 20개가 기다리고 있어요!"

        self.assertFalse(is_whitelisted(text))
        self.assertTrue(is_review_spam(text))

    def test_aliexpress_delivery_notice_stays_whitelisted(self):
        text = "[AliExpress] 주문 상품이 배송 중입니다"

        self.assertTrue(is_whitelisted(text))
        self.assertFalse(is_review_spam(text))


class AlarmSummaryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_tokens_do_not_include_ellipsis(self):
        deps = _AlarmSummaryDeps(
            build_stop_tokens=MagicMock(return_value=["Okay", "let me", "\n\n\n", "aaaa", "----"]),
            resolve_llm_options=MagicMock(
                return_value=MagicMock(
                    max_tokens=512,
                    temperature=0.05,
                    enable_thinking=False,
                    extra_kwargs={},
                )
            ),
            generate_with_main_llm_async=AsyncMock(return_value="- 치지직에서 [민트초코용...님 라이브 시작!]"),
            dump_llm_draft=MagicMock(),
            sanitize_llm_output=MagicMock(side_effect=lambda items, text: text),
            postprocess_llm_text=MagicMock(side_effect=lambda text: text),
            get_korean_ratio=MagicMock(return_value=1.0),
        )

        items = [
            {
                "app_name": "치지직",
                "app_title": "민트초코용...님 라이브 시작!",
                "conversation": "",
                "text": "민트초코용...님이 방송을 시작했습니다",
            }
        ]

        result = await _generate_alarm_summary_async(
            items,
            "prompt",
            deps=deps,
        )

        self.assertEqual(result, "- 치지직에서 [민트초코용...님 라이브 시작!]")
        deps.build_stop_tokens.assert_called_once_with(extra=["\n\n\n", "aaaa", "----"])
        deps.resolve_llm_options.assert_called_once_with(
            {},
            default_max_tokens=ALARM_SUMMARY_DEFAULT_MAX_TOKENS,
            default_temperature=0.05,
        )
        stop_tokens = deps.generate_with_main_llm_async.await_args.kwargs["stop"]
        self.assertNotIn("...", stop_tokens)

    async def test_default_output_budget_is_roomy_for_paid_chat_completion(self):
        deps = _AlarmSummaryDeps(
            build_stop_tokens=MagicMock(return_value=["\n\n\n", "aaaa", "----"]),
            resolve_llm_options=MagicMock(
                return_value=MagicMock(
                    max_tokens=ALARM_SUMMARY_DEFAULT_MAX_TOKENS,
                    temperature=0.05,
                    enable_thinking=False,
                    extra_kwargs={},
                )
            ),
            generate_with_main_llm_async=AsyncMock(return_value="- 문피아에서 새 회차 등록"),
            dump_llm_draft=MagicMock(),
            sanitize_llm_output=MagicMock(side_effect=lambda items, text: text),
            postprocess_llm_text=MagicMock(side_effect=lambda text: text),
            get_korean_ratio=MagicMock(return_value=1.0),
        )

        result = await _generate_alarm_summary_async(
            [{"app_name": "문피아", "app_title": "업데이트", "conversation": "", "text": "새 회차 등록"}],
            "prompt",
            deps=deps,
        )

        self.assertEqual(result, "- 문피아에서 새 회차 등록")
        self.assertEqual(
            deps.generate_with_main_llm_async.await_args.kwargs["max_tokens"],
            ALARM_SUMMARY_DEFAULT_MAX_TOKENS,
        )


if __name__ == "__main__":
    unittest.main()
