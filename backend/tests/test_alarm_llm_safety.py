import os
import tempfile
import unittest
import asyncio
import pytest
from unittest.mock import patch


os.environ.setdefault("DATABASE_URL", "sqlite:////home/dlckdgn/personal-portfolio/devplan/test_db/test.db")
os.environ.setdefault("API_TOKEN", "test-token")


from backend.services.alarm.sanitizer import sanitize_llm_output  # noqa: E402
from backend.services.alarm.llm_logic import summarize_with_llm  # noqa: E402


class _StubLLMService:
    def __init__(self, response: str):
        self.response = response
        self._base_url = None
        self._model = object()

    def _is_remote_mode(self):
        return False

    def is_loaded(self):
        return True

    def generate_chat(self, messages, **kwargs):
        return self.response


@pytest.mark.integration
class AlarmLLMSafetyTests(unittest.TestCase):
    def tearDown(self):
        from backend.services.llm.service import LLMService
        LLMService._instance = None

    def test_sanitize_drops_hallucinated_app_label(self) -> None:
        original_items = [
            {"app_name": "카카오톡", "sender": "이*후", "text": "이*후님: 내일 영화 보러 갈래?"}
        ]
        llm_output = "- [배달앱] 오늘 12시에 신제품 김치 배달이 예정되어 있습니다."
        self.assertEqual(sanitize_llm_output(original_items, llm_output), "")

    def test_sanitize_drops_ungrounded_content_even_with_same_app(self) -> None:
        original_items = [
            {"app_name": "배달의민족", "text": "주문번호 [식별번호] 배달이 완료되었습니다."}
        ]
        llm_output = "- [배달의민족] 오늘 12시에 신제품 김치 배달이 예정되어 있습니다."
        self.assertEqual(sanitize_llm_output(original_items, llm_output), "")

    def test_summarize_with_llm_falls_back_to_real_notifications(self) -> None:
        items = [
            {
                "app_name": "카카오톡",
                "package": "com.kakao.talk",
                "sender": "이*후",
                "text": "이*후님: 내일 영화 보러 갈래?",
            }
        ]
        stub = _StubLLMService("- [카카오톡] 이*후님이 영화 보러 가자고 하네요.")
        with patch("backend.services.alarm.llm_logic.LLMService.get_instance", return_value=stub):
            result = asyncio.run(summarize_with_llm(items))
        self.assertIn("카카오톡", result)
        self.assertIn("영화", result)
        self.assertNotIn("배달앱", result)

    def test_summarize_with_llm_falls_back_when_llm_output_is_too_weak(self) -> None:
        items = [
            {
                "app_name": "LPL",
                "sender": "[LPL WBG vs TES] 크렘 vs 샤오후, 엘크",
                "app_title": "[LPL WBG vs TES] 크렘 vs 샤오후, 엘크  #LPLCostream  #감컴, 포더엠",
                "text": "지금 경기 시작!",
            }
        ]
        stub = _StubLLMService("- 아니다")

        async def _fake_to_thread(func, /, *args, **kwargs):
            return func(*args, **kwargs)

        with (
            patch("backend.services.alarm.llm_logic.LLMService.get_instance", return_value=stub),
            patch("backend.services.alarm.llm_refiner.asyncio.to_thread", side_effect=_fake_to_thread),
        ):
            result = asyncio.run(summarize_with_llm(items))

        self.assertIn("WBG", result)
        self.assertNotIn("아니다", result)

    def test_summarize_with_llm_falls_back_when_count_only_summary(self) -> None:
        items = [
            {
                "app_name": "Gmail",
                "sender": "Google",
                "app_title": "영수증: 1월 정기결제 안내",
                "conversation": "",
                "text": "이번 달 결제 내역을 확인하세요.",
            },
            {
                "app_name": "Gmail",
                "sender": "Google",
                "app_title": "보안 알림: 새 로그인 감지",
                "conversation": "",
                "text": "새 기기에서 로그인 시도가 있었습니다.",
            },
            {
                "app_name": "Gmail",
                "sender": "Google",
                "app_title": "배송 안내: 주문이 발송되었습니다",
                "conversation": "",
                "text": "배송 상태를 확인하세요.",
            },
        ]
        stub = _StubLLMService("- 메일 3건이 있었어요")

        async def _fake_to_thread(func, /, *args, **kwargs):
            return func(*args, **kwargs)

        with (
            patch("backend.services.alarm.llm_logic.LLMService.get_instance", return_value=stub),
            patch("backend.services.alarm.llm_refiner.asyncio.to_thread", side_effect=_fake_to_thread),
        ):
            result = asyncio.run(summarize_with_llm(items))

        self.assertIn("정기결제", result)
        self.assertNotIn("메일 3건", result)
