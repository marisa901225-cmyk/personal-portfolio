import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from backend.services.news.weather_message import generate_weather_message_with_llm


class _FakeLLM:
    def __init__(
        self,
        *,
        paid_responses=None,
        chat_responses=None,
        is_paid_configured=True,
        is_remote_configured=True,
    ):
        self.settings = SimpleNamespace(
            ai_report_model="gpt-5.4",
            ai_report_api_key="ai-report-key",
            ai_report_base_url="https://api.openai.com/v1",
            is_paid_configured=lambda: is_paid_configured,
            is_remote_configured=lambda: is_remote_configured,
        )
        self._paid_responses = list(paid_responses or [])
        self._chat_responses = list(chat_responses or [])
        self.paid_calls = []
        self.chat_calls = []

    def generate_paid_chat(self, messages, **kwargs):
        self.paid_calls.append({"messages": messages, **kwargs})
        if self._paid_responses:
            return self._paid_responses.pop(0)
        return ""

    def generate_chat(self, messages, **kwargs):
        self.chat_calls.append({"messages": messages, **kwargs})
        if self._chat_responses:
            return self._chat_responses.pop(0)
        return ""

    def get_last_error(self):
        return None


class WeatherMessageRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def _render(self, fake_llm, *, open_api_key="openrouter-key"):
        fake_settings = SimpleNamespace(
            open_api_key=open_api_key,
            morning_openrouter_model="google/gemini-3-flash-preview",
            morning_openrouter_base_url="https://openrouter.ai/api/v1",
            morning_allow_paid_fallback=False,
        )
        valid_text = "오늘 서울은 17도고 낮 최고기온은 22도야. 하늘은 구름이 많고 강수확률도 낮은 편이야."

        with patch("backend.services.news.weather_message.settings", fake_settings):
            with patch("backend.services.news.weather_message.LLMService.get_instance", return_value=fake_llm):
                with patch("backend.services.news.weather_message.load_prompt", return_value="test prompt"):
                    with patch("backend.services.news.weather_message.load_persona_profile", return_value=("테스트", "")):
                        with patch("backend.services.news.weather_message.clean_exaone_tokens", side_effect=lambda text: text):
                            message = await generate_weather_message_with_llm(
                                temp="17",
                                weather_status="구름많음",
                                pop="20",
                                base_date="20260415",
                                base_time="0730",
                                max_temp="22",
                                ultra_short_data="기온: 17°C | 하늘/강수: 구름많음",
                            )

        return message, valid_text

    async def test_weather_message_prefers_ai_report_before_openrouter(self):
        valid_text = "오늘 서울은 17도고 낮 최고기온은 22도야. 하늘은 구름이 많고 강수확률도 낮은 편이야."
        fake_llm = _FakeLLM(paid_responses=[valid_text], is_paid_configured=True, is_remote_configured=True)

        message, _ = await self._render(fake_llm)

        self.assertIn("17도", message)
        self.assertEqual(len(fake_llm.paid_calls), 1)
        self.assertEqual(fake_llm.paid_calls[0]["model"], "gpt-5.4")
        self.assertEqual(fake_llm.paid_calls[0]["api_key"], "ai-report-key")
        self.assertEqual(fake_llm.paid_calls[0]["base_url"], "https://api.openai.com/v1")
        self.assertEqual(fake_llm.chat_calls, [])

    async def test_weather_message_uses_openrouter_as_paid_fallback(self):
        valid_text = "오늘 서울은 17도고 낮 최고기온은 22도야. 하늘은 구름이 많고 강수확률도 낮은 편이야."
        fake_llm = _FakeLLM(paid_responses=["", valid_text], is_paid_configured=True, is_remote_configured=True)

        message, _ = await self._render(fake_llm)

        self.assertIn("17도", message)
        self.assertEqual(len(fake_llm.paid_calls), 2)
        self.assertEqual(fake_llm.paid_calls[0]["model"], "gpt-5.4")
        self.assertEqual(fake_llm.paid_calls[1]["model"], "google/gemini-3-flash-preview")
        self.assertEqual(fake_llm.paid_calls[1]["api_key"], "openrouter-key")
        self.assertEqual(fake_llm.paid_calls[1]["base_url"], "https://openrouter.ai/api/v1")
        self.assertEqual(fake_llm.chat_calls, [])

    async def test_weather_message_falls_back_to_remote_after_paid_failures(self):
        valid_text = "오늘 서울은 17도고 낮 최고기온은 22도야. 하늘은 구름이 많고 강수확률도 낮은 편이야."
        fake_llm = _FakeLLM(
            paid_responses=["", ""],
            chat_responses=[valid_text],
            is_paid_configured=True,
            is_remote_configured=True,
        )

        message, _ = await self._render(fake_llm)

        self.assertIn("17도", message)
        self.assertEqual(len(fake_llm.paid_calls), 2)
        self.assertEqual(len(fake_llm.chat_calls), 1)
        self.assertFalse(fake_llm.chat_calls[0]["allow_paid_fallback"])

    async def test_weather_message_uses_fallback_message_when_no_backend_is_configured(self):
        fake_llm = _FakeLLM(
            paid_responses=[],
            chat_responses=[],
            is_paid_configured=False,
            is_remote_configured=False,
        )

        message, _ = await self._render(fake_llm, open_api_key=None)

        self.assertIn("[오늘의 날씨 정보 - 서울]", message)
        self.assertEqual(fake_llm.paid_calls, [])
        self.assertEqual(fake_llm.chat_calls, [])
