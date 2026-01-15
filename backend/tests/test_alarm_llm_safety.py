import os
import tempfile
import unittest
import asyncio
from unittest.mock import patch


_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_temp_dir.name}/test.db")
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

    def generate_chat(self, messages, max_tokens=512, temperature=0.7, stop=None, seed=None, enable_thinking=False):
        return self.response


class AlarmLLMSafetyTests(unittest.TestCase):
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
        stub = _StubLLMService("- [배달앱] 오늘 12시에 신제품 김치 배달이 예정되어 있습니다.")
        with patch("backend.services.alarm.llm_logic.LLMService.get_instance", return_value=stub):
            result = asyncio.run(summarize_with_llm(items))
        self.assertIn("카카오톡", result)
        self.assertIn("영화", result)
        self.assertNotIn("배달앱", result)

