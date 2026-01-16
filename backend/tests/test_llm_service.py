# backend/tests/test_llm_service.py
import os
import unittest
from unittest.mock import patch

from backend.services.llm.service import LLMService
from backend.services.llm.backends.remote import RemoteLlamaBackend
from backend.services.llm.backends.paid import OpenAIPaidBackend


class TestLLMService(unittest.TestCase):
    def tearDown(self):
        LLMService._instance = None

    def test_generate_chat_uses_paid_when_remote_not_configured(self):
        env = {
            "AI_REPORT_API_KEY": "test-key",
            "AI_REPORT_BASE_URL": "https://api.openai.com/v1",
            "AI_REPORT_MODEL": "gpt-5.2",
        }

        with patch.dict(os.environ, env, clear=True):
            with patch.object(RemoteLlamaBackend, "chat", side_effect=AssertionError("remote should not be used")):
                with patch.object(OpenAIPaidBackend, "chat", return_value="paid-ok") as paid_chat:
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "paid-ok")
                    paid_chat.assert_called()

    def test_generate_chat_prefers_remote_when_configured(self):
        env = {
            "LLM_BASE_URL": "http://localhost:8080",
            "AI_REPORT_API_KEY": "test-key",
            "AI_REPORT_BASE_URL": "https://api.openai.com/v1",
            "AI_REPORT_MODEL": "gpt-5.2",
        }

        with patch.dict(os.environ, env, clear=True):
            with patch.object(RemoteLlamaBackend, "chat", return_value="remote-ok") as remote_chat:
                with patch.object(OpenAIPaidBackend, "chat", side_effect=AssertionError("paid should not be used")):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "remote-ok")
                    remote_chat.assert_called()

    def test_generate_chat_falls_back_to_paid_on_remote_failure(self):
        env = {
            "LLM_BASE_URL": "http://localhost:8080",
            "AI_REPORT_API_KEY": "test-key",
            "AI_REPORT_BASE_URL": "https://api.openai.com/v1",
            "AI_REPORT_MODEL": "gpt-5.2",
        }

        def _remote_fail(*args, **kwargs):
            return ""

        with patch.dict(os.environ, env, clear=True):
            with patch.object(RemoteLlamaBackend, "chat", new=_remote_fail):
                with patch.object(OpenAIPaidBackend, "chat", return_value="paid-ok"):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "paid-ok")  # 순수 텍스트 (💰는 전송 단계에서만)
                    self.assertIsNone(llm.get_last_error())

    def test_no_backend_configured_returns_empty_and_sets_error(self):
        with patch.dict(os.environ, {}, clear=True):
            llm = LLMService.get_instance()
            out = llm.generate_chat([{"role": "user", "content": "hi"}])
            self.assertEqual(out, "")
            self.assertIn("No LLM backend configured", llm.get_last_error())


if __name__ == "__main__":
    unittest.main()
