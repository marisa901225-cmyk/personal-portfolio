import unittest
from contextlib import ExitStack
from datetime import datetime as real_datetime
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.alarm import llm_logic, llm_logic_v2


class _StubLLM:
    def __init__(self, loaded: bool, *, used_paid: bool = False) -> None:
        self._loaded = loaded
        self._used_paid = used_paid
        self.reset_context = MagicMock()

    def is_loaded(self) -> bool:
        return self._loaded

    def last_used_paid(self) -> bool:
        return self._used_paid


class AlarmLlmLogicV2ParityTests(unittest.IsolatedAsyncioTestCase):
    def _patch_both(self, stack: ExitStack, attr: str, *, new):
        stack.enter_context(patch.object(llm_logic, attr, new=new))
        stack.enter_context(patch.object(llm_logic_v2, attr, new=new))

    async def test_no_llm_returns_same_notification_lines(self):
        items = [
            {"app_title": "카카오톡", "conversation": "민수", "text": "점심 먹자"},
            {"app_title": "카카오톡", "conversation": "민수", "text": "점심 먹자"},
            {"app_title": "%숨김", "conversation": "%대화", "text": "배송 완료"},
        ]
        stub = _StubLLM(loaded=False)

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))

            result_v1 = await llm_logic.summarize_with_llm(items)
            result_v2 = await llm_logic_v2.summarize_with_llm(items)

        self.assertEqual(result_v1, result_v2)

    async def test_random_message_matches_v1_behavior(self):
        stub = _StubLLM(loaded=True)
        fixed_now = real_datetime(2026, 3, 12, 12, 0, 0)
        draft = (
            "역사 이야기를 아주 길게 풀어보자. 키워드 하나와 키워드 둘을 반드시 담고, "
            "한국어로만 자연스럽게 이어 가는 문장을 충분히 길게 적는다. "
            "이 문장은 테스트를 위해 100자 이상이 되도록 조금 더 길게 늘려서 쓴다."
        )

        fake_datetime_v1 = MagicMock()
        fake_datetime_v1.now.return_value = fixed_now
        fake_datetime_v2 = MagicMock()
        fake_datetime_v2.now.return_value = fixed_now

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic, "datetime", fake_datetime_v1))
            stack.enter_context(patch.object(llm_logic_v2, "datetime", fake_datetime_v2))

            for module in (llm_logic, llm_logic_v2):
                stack.enter_context(patch.object(module, "get_all_categories", return_value=["역사/문화", "우주/천문학"]))
                stack.enter_context(patch.object(module, "get_formats", return_value=["질문형"]))
                stack.enter_context(patch.object(module, "get_openers", return_value=["오프너"]))
                stack.enter_context(patch.object(module, "get_twists", return_value=["트위스트"]))
                stack.enter_context(patch.object(module, "get_voices", return_value={"차분한 목소리": "침착하게 말해"}))
                stack.enter_context(patch.object(module, "load_recent_categories", return_value=[]))
                stack.enter_context(patch.object(module, "pick_keywords_for_constraints", return_value=["키워드 하나", "키워드 둘"]))
                stack.enter_context(patch.object(module, "get_category_keywords", return_value={}))
                stack.enter_context(
                    patch.object(
                        module,
                        "load_prompt",
                        side_effect=lambda key, **kwargs: "system prompt" if key == "random_topic_system" else "user prompt",
                    )
                )
                stack.enter_context(patch.object(module, "dump_llm_draft", MagicMock()))
                stack.enter_context(patch.object(module, "save_recent_category", MagicMock()))
                stack.enter_context(patch.object(module, "save_last_random_topic_sent_at", MagicMock()))
                stack.enter_context(patch.object(module.random, "choice", side_effect=lambda seq: seq[0]))
                stack.enter_context(patch.object(module.random, "shuffle", side_effect=lambda seq: None))
                stack.enter_context(patch.object(module, "generate_with_main_llm_async", new=AsyncMock(return_value=draft)))
                stack.enter_context(patch.object(module, "refine_draft_with_light_llm_async", new=AsyncMock(return_value=draft)))
                stack.enter_context(patch.object(module, "has_category_anchor", return_value=True))

            result_v1 = await llm_logic.summarize_with_llm([])
            result_v2 = await llm_logic_v2.summarize_with_llm([])

        self.assertEqual(result_v1, result_v2)

    async def test_alarm_summary_matches_v1_behavior(self):
        stub = _StubLLM(loaded=True)
        items = [
            {"app_title": "쿠팡", "conversation": "", "text": "상품이 배송 완료되었습니다"},
            {"app_title": "카드", "conversation": "", "text": "결제 승인 12,000원"},
        ]
        summary = "- 배송 완료\n- 결제 승인 12,000원"

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))

            for module in (llm_logic, llm_logic_v2):
                stack.enter_context(patch.object(module, "load_prompt", return_value="alarm prompt"))
                stack.enter_context(patch.object(module, "dump_llm_draft", MagicMock()))
                stack.enter_context(patch.object(module, "generate_with_main_llm_async", new=AsyncMock(return_value=summary)))
                stack.enter_context(patch.object(module, "sanitize_llm_output", side_effect=lambda src_items, text: text))

            result_v1 = await llm_logic.summarize_with_llm(items)
            result_v2 = await llm_logic_v2.summarize_with_llm(items)

        self.assertEqual(result_v1, result_v2)

    async def test_expense_summary_matches_v1_behavior(self):
        stub = _StubLLM(loaded=True)
        expenses = [
            {"merchant": "라멘집", "amount": -12000, "category": "식비"},
            {"merchant": "서점", "amount": -18000, "category": "취미"},
        ]
        reply = "지출 흐름이 꽤 인간적이네."

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic, "generate_with_main_llm_async", new=AsyncMock(return_value=reply)))
            stack.enter_context(patch.object(llm_logic_v2, "generate_with_main_llm_async", new=AsyncMock(return_value=reply)))

            result_v1 = await llm_logic.summarize_expenses_with_llm(expenses)
            result_v2 = await llm_logic_v2.summarize_expenses_with_llm(expenses)

        self.assertEqual(result_v1, result_v2)

    async def test_random_message_retries_when_replacement_char_remains(self):
        stub = _StubLLM(loaded=True)
        fixed_now = real_datetime(2026, 3, 12, 9, 50, 0)
        broken_draft = (
            "VHS \ufffdape 이야기를 길게 풀어 보자. 키워드 하나와 키워드 둘을 담고, "
            "한국어 문장을 충분히 길게 이어 가서 테스트 길이를 만족시키는 초안이다. "
            "하지만 깨진 문자가 남아 있어서 이 시도는 통과하면 안 된다."
        )
        clean_draft = (
            "VHS 테이프 이야기를 길게 풀어 보자. 키워드 하나와 키워드 둘을 담고, "
            "한국어 문장을 충분히 길게 이어 가서 테스트 길이를 만족시키는 초안이다. "
            "이번에는 깨진 문자가 없어 정상적으로 통과해야 한다."
        )

        fake_datetime = MagicMock()
        fake_datetime.now.return_value = fixed_now

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "datetime", fake_datetime))
            stack.enter_context(patch.object(llm_logic_v2, "get_all_categories", return_value=["영화/드라마/음악"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_formats", return_value=["질문형"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_openers", return_value=["오프너"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_twists", return_value=["트위스트"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_voices", return_value={"차분한 목소리": "침착하게 말해"}))
            stack.enter_context(patch.object(llm_logic_v2, "load_recent_categories", return_value=[]))
            stack.enter_context(patch.object(llm_logic_v2, "pick_keywords_for_constraints", return_value=["키워드 하나", "키워드 둘"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_category_keywords", return_value={}))
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "load_prompt",
                    side_effect=lambda key, **kwargs: "system prompt" if key == "random_topic_system" else "user prompt",
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "dump_llm_draft", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_recent_category", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_last_random_topic_sent_at", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2.random, "choice", side_effect=lambda seq: seq[0]))
            stack.enter_context(patch.object(llm_logic_v2.random, "shuffle", side_effect=lambda seq: None))
            generate_mock = AsyncMock(side_effect=[broken_draft, clean_draft, "깨진 VHS 메모"])
            refine_mock = AsyncMock(side_effect=[broken_draft, clean_draft])
            stack.enter_context(patch.object(llm_logic_v2, "generate_with_main_llm_async", new=generate_mock))
            stack.enter_context(patch.object(llm_logic_v2, "refine_draft_with_light_llm_async", new=refine_mock))
            stack.enter_context(patch.object(llm_logic_v2, "has_category_anchor", return_value=True))

            result = await llm_logic_v2.summarize_with_llm([])

        self.assertEqual(result, clean_draft)
        self.assertEqual(generate_mock.await_count, 3)

    async def test_random_message_retries_when_explanatory_tail_remains(self):
        stub = _StubLLM(loaded=True)
        fixed_now = real_datetime(2026, 3, 12, 10, 0, 0)
        explanatory_tail_draft = (
            "카세트테이프가 냄비처럼 보글거리며 오늘의 메뉴를 낭독했다는 식으로 시작한다. "
            "키워드 하나와 키워드 둘을 묶어 밤참 같은 사건으로 키우고, 골목 불빛까지 끌어와 충분히 길게 서사를 이어 간다. "
            "결론적으로 우리는 추억을 천천히 한 입만 씹으시길 바랍니다."
        )
        punchline_draft = (
            "카세트테이프가 냄비처럼 보글거리며 오늘의 메뉴를 낭독했다는 식으로 시작한다. "
            "키워드 하나와 키워드 둘을 묶어 밤참 같은 사건으로 키우고, 골목 불빛까지 끌어와 충분히 길게 서사를 이어 간다. "
            "그랬더니 테이프가 마지막에 면치기 소리까지 흉내 내서, 동네 전체가 야식 광고인 척 연기하다 퇴근했다."
        )

        fake_datetime = MagicMock()
        fake_datetime.now.return_value = fixed_now

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "datetime", fake_datetime))
            stack.enter_context(patch.object(llm_logic_v2, "get_all_categories", return_value=["영화/드라마/음악"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_formats", return_value=["질문형"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_openers", return_value=["오프너"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_twists", return_value=["트위스트"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_voices", return_value={"차분한 목소리": "침착하게 말해"}))
            stack.enter_context(patch.object(llm_logic_v2, "load_recent_categories", return_value=[]))
            stack.enter_context(patch.object(llm_logic_v2, "pick_keywords_for_constraints", return_value=["키워드 하나", "키워드 둘"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_category_keywords", return_value={}))
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "load_prompt",
                    side_effect=lambda key, **kwargs: "system prompt" if key == "random_topic_system" else "user prompt",
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "dump_llm_draft", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_recent_category", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_last_random_topic_sent_at", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2.random, "choice", side_effect=lambda seq: seq[0]))
            stack.enter_context(patch.object(llm_logic_v2.random, "shuffle", side_effect=lambda seq: None))
            generate_mock = AsyncMock(side_effect=[explanatory_tail_draft, punchline_draft, "카세트 야식 소동"])
            stack.enter_context(patch.object(llm_logic_v2, "generate_with_main_llm_async", new=generate_mock))
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "refine_draft_with_light_llm_async",
                    new=AsyncMock(side_effect=[explanatory_tail_draft, punchline_draft]),
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "has_category_anchor", return_value=True))

            result = await llm_logic_v2.summarize_with_llm([])

        self.assertEqual(result, punchline_draft)
        self.assertEqual(generate_mock.await_count, 3)

    async def test_generate_random_message_payload_uses_paid_single_call_title_and_body(self):
        stub = _StubLLM(loaded=True, used_paid=True)
        fixed_now = real_datetime(2026, 3, 12, 12, 20, 0)
        draft = (
            "폴라로이드 사진이 미래 뉴스를 들고 와 버렸다는 식으로 시작한다. "
            "키워드 하나와 키워드 둘을 묶어 황당한 사건처럼 풀어내고, 마지막은 핫픽스 완료 같은 식으로 끝낸다. "
            "테스트용이라도 충분히 길게 적어서 길이 제한을 무난히 통과하게 만든다."
        )
        title = "폴라로이드 핫픽스"
        paid_payload = f"제목: {title}\n본문:\n{draft}"

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "get_all_categories", return_value=["폴라로이드 추억/기묘한 타임슬립"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_formats", return_value=["미래 뉴스 속보 형식으로 시작해라"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_openers", return_value=["자, 지금이 아니면 절대 들을 수 없는 이야기!"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_twists", return_value=["마지막 문장에서 이야기를 갑자기 철학적으로 뒤집어라."]))
            stack.enter_context(patch.object(llm_logic_v2, "get_voices", return_value={"코딩하는 점술가": "핫픽스 완료 같은 선언으로 끝낸다."}))
            stack.enter_context(patch.object(llm_logic_v2, "load_recent_categories", return_value=[]))
            stack.enter_context(patch.object(llm_logic_v2, "pick_keywords_for_constraints", return_value=["키워드 하나", "키워드 둘"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_category_keywords", return_value={}))
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "load_prompt",
                    side_effect=lambda key, **kwargs: f"{key} prompt",
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "dump_llm_draft", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_recent_category", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_last_random_topic_sent_at", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2.random, "choice", side_effect=lambda seq: seq[0]))
            stack.enter_context(patch.object(llm_logic_v2.random, "shuffle", side_effect=lambda seq: None))
            generate_mock = AsyncMock(return_value=paid_payload)
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "generate_with_main_llm_async",
                    new=generate_mock,
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "refine_draft_with_light_llm_async", new=AsyncMock(return_value=draft)))
            stack.enter_context(patch.object(llm_logic_v2, "has_category_anchor", return_value=True))

            payload = await llm_logic_v2.generate_random_message_payload(now=fixed_now)

        self.assertEqual(payload, {"title": title, "body": draft})
        self.assertEqual(generate_mock.await_args_list[0].kwargs["paid_system_prompt"], "random_topic_gpt5_paid_system prompt")
        self.assertEqual(generate_mock.await_count, 1)

    async def test_generate_random_message_payload_keeps_second_title_call_for_local_route(self):
        stub = _StubLLM(loaded=True, used_paid=False)
        fixed_now = real_datetime(2026, 3, 12, 12, 20, 0)
        draft = (
            "폴라로이드 사진이 미래 뉴스를 들고 와 버렸다는 식으로 시작한다. "
            "키워드 하나와 키워드 둘을 묶어 황당한 사건처럼 풀어내고, 마지막은 핫픽스 완료 같은 식으로 끝낸다. "
            "테스트용이라도 충분히 길게 적어서 길이 제한을 무난히 통과하게 만든다."
        )
        title = "폴라로이드 핫픽스"

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "get_all_categories", return_value=["폴라로이드 추억/기묘한 타임슬립"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_formats", return_value=["미래 뉴스 속보 형식으로 시작해라"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_openers", return_value=["자, 지금이 아니면 절대 들을 수 없는 이야기!"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_twists", return_value=["마지막 문장에서 이야기를 갑자기 철학적으로 뒤집어라."]))
            stack.enter_context(patch.object(llm_logic_v2, "get_voices", return_value={"코딩하는 점술가": "핫픽스 완료 같은 선언으로 끝낸다."}))
            stack.enter_context(patch.object(llm_logic_v2, "load_recent_categories", return_value=[]))
            stack.enter_context(patch.object(llm_logic_v2, "pick_keywords_for_constraints", return_value=["키워드 하나", "키워드 둘"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_category_keywords", return_value={}))
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "load_prompt",
                    side_effect=lambda key, **kwargs: f"{key} prompt",
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "dump_llm_draft", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_recent_category", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_last_random_topic_sent_at", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2.random, "choice", side_effect=lambda seq: seq[0]))
            stack.enter_context(patch.object(llm_logic_v2.random, "shuffle", side_effect=lambda seq: None))
            generate_mock = AsyncMock(side_effect=[draft, title])
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "generate_with_main_llm_async",
                    new=generate_mock,
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "refine_draft_with_light_llm_async", new=AsyncMock(return_value=draft)))
            stack.enter_context(patch.object(llm_logic_v2, "has_category_anchor", return_value=True))

            payload = await llm_logic_v2.generate_random_message_payload(now=fixed_now)

        self.assertEqual(payload, {"title": title, "body": draft})
        self.assertEqual(generate_mock.await_args_list[0].kwargs["paid_system_prompt"], "random_topic_gpt5_paid_system prompt")
        self.assertEqual(generate_mock.await_args_list[1].kwargs["reasoning_effort"], "none")
        self.assertEqual(generate_mock.await_args_list[1].kwargs["paid_system_prompt"], "random_topic_title_gpt5_paid_system prompt")


class AlarmLlmLogicV2WeekendTests(unittest.IsolatedAsyncioTestCase):
    async def test_random_message_allows_exactly_at_weekday_6pm(self):
        stub = _StubLLM(loaded=True)
        weekday_six_pm = real_datetime(2026, 3, 13, 18, 0, 0)
        fake_datetime = MagicMock()
        fake_datetime.now.return_value = weekday_six_pm

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "datetime", fake_datetime))
            stack.enter_context(patch.object(llm_logic_v2, "get_all_categories", return_value=["역사/문화"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_formats", return_value=["질문형"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_openers", return_value=["오프너"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_twists", return_value=["트위스트"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_voices", return_value={"차분한 목소리": "침착하게 말해"}))
            stack.enter_context(patch.object(llm_logic_v2, "load_recent_categories", return_value=[]))
            stack.enter_context(patch.object(llm_logic_v2, "pick_keywords_for_constraints", return_value=["키워드 하나", "키워드 둘"]))
            stack.enter_context(patch.object(llm_logic_v2, "get_category_keywords", return_value={}))
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "load_prompt",
                    side_effect=lambda key, **kwargs: "system prompt" if key == "random_topic_system" else "user prompt",
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "dump_llm_draft", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_recent_category", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2, "save_last_random_topic_sent_at", MagicMock()))
            stack.enter_context(patch.object(llm_logic_v2.random, "choice", side_effect=lambda seq: seq[0]))
            stack.enter_context(patch.object(llm_logic_v2.random, "shuffle", side_effect=lambda seq: None))
            draft_text = (
                "역사 이야기를 길게 풀어 보자. 키워드 하나와 키워드 둘을 담고, "
                "한국어 문장을 충분히 이어 가서 길이 제한도 무난히 넘기는 테스트용 초안이다. "
                "평일 오후 여섯 시 정각에는 아직 랜덤 메시지가 살아 있어야 한다는 조건을 검증하려고 "
                "문장을 조금 더 덧붙여서 실제 생성 규칙의 최소 길이도 안정적으로 통과하게 만든다."
            )
            draft = AsyncMock(side_effect=[draft_text, "여섯 시 브리핑"])
            stack.enter_context(patch.object(llm_logic_v2, "generate_with_main_llm_async", new=draft))
            stack.enter_context(
                patch.object(
                    llm_logic_v2,
                    "refine_draft_with_light_llm_async",
                    new=AsyncMock(side_effect=lambda text, **kwargs: text),
                )
            )
            stack.enter_context(patch.object(llm_logic_v2, "has_category_anchor", return_value=True))

            result = await llm_logic_v2.summarize_with_llm([])

        self.assertIsInstance(result, str)
        self.assertTrue(result)
        draft.assert_awaited()

    async def test_random_message_skips_after_weekday_6pm(self):
        stub = _StubLLM(loaded=True)
        weekday_after_six_pm = real_datetime(2026, 3, 13, 18, 10, 0)
        fake_datetime = MagicMock()
        fake_datetime.now.return_value = weekday_after_six_pm

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "datetime", fake_datetime))
            generate_mock = AsyncMock(return_value="오후 6시 이후 랜덤 메시지")
            stack.enter_context(patch.object(llm_logic_v2, "generate_with_main_llm_async", new=generate_mock))

            result = await llm_logic_v2.summarize_with_llm([])

        self.assertIsNone(result)
        generate_mock.assert_not_awaited()

    async def test_random_message_skips_on_weekend(self):
        stub = _StubLLM(loaded=True)
        saturday_noon = real_datetime(2026, 3, 14, 12, 0, 0)
        fake_datetime = MagicMock()
        fake_datetime.now.return_value = saturday_noon

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "datetime", fake_datetime))
            generate_mock = AsyncMock(return_value="주말 랜덤 메시지")
            stack.enter_context(patch.object(llm_logic_v2, "generate_with_main_llm_async", new=generate_mock))

            result = await llm_logic_v2.summarize_with_llm([])

        self.assertIsNone(result)
        generate_mock.assert_not_awaited()

    async def test_random_message_skips_on_kr_public_holiday(self):
        stub = _StubLLM(loaded=True)
        independence_day_morning = real_datetime(2026, 3, 1, 10, 0, 0)
        fake_datetime = MagicMock()
        fake_datetime.now.return_value = independence_day_morning

        with ExitStack() as stack:
            stack.enter_context(patch.object(llm_logic_v2.LLMService, "get_instance", return_value=stub))
            stack.enter_context(patch.object(llm_logic_v2, "datetime", fake_datetime))
            generate_mock = AsyncMock(return_value="공휴일 랜덤 메시지")
            stack.enter_context(patch.object(llm_logic_v2, "generate_with_main_llm_async", new=generate_mock))

            result = await llm_logic_v2.summarize_with_llm([])

        self.assertIsNone(result)
        generate_mock.assert_not_awaited()
