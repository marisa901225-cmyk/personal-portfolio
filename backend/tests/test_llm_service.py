import os
import unittest
from unittest.mock import patch

from backend.services.llm.service import LLMService
from backend.services.llm.config import Settings
from backend.services.llm.backends.remote import RemoteLlamaBackend
from backend.services.llm.backends.paid import OpenAIPaidBackend
from backend.tests.llm_test_helpers import patched_llm_settings


class TestLLMService(unittest.TestCase):
    def tearDown(self):
        LLMService._instance = None

    def test_settings_backend_dir_points_to_backend_directory(self):
        expected_backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        settings = Settings()

        self.assertEqual(settings.backend_dir_abs, expected_backend_dir)
        self.assertEqual(settings.data_dir_abs, os.path.join(expected_backend_dir, "data"))

    def test_generate_chat_uses_paid_when_remote_not_configured(self):
        with patched_llm_settings(
            ai_report_model="gpt-5.2",
            ai_report_fallback_model="gpt-5.4-mini",
        ):
            with patch.object(RemoteLlamaBackend, "chat", side_effect=AssertionError("remote should not be used")):
                with patch.object(OpenAIPaidBackend, "chat", return_value="paid-ok") as paid_chat:
                    llm = LLMService.get_instance()
                    response_format = {
                        "type": "json_schema",
                        "json_schema": {"name": "t", "strict": True, "schema": {"type": "object"}},
                    }
                    out = llm.generate_chat(
                        [{"role": "user", "content": "hi"}],
                        stop=["STOP"],
                        seed=7,
                        service_tier="flex",
                        response_format=response_format,
                    )
                    self.assertEqual(out, "paid-ok")
                    paid_chat.assert_called()
                    _, called_kwargs = paid_chat.call_args
                    self.assertEqual(called_kwargs.get("stop"), ["STOP"])
                    self.assertEqual(called_kwargs.get("seed"), 7)
                    self.assertEqual(called_kwargs.get("service_tier"), "flex")
                    self.assertEqual(called_kwargs.get("response_format"), response_format)

    def test_generate_chat_prefers_remote_when_configured(self):
        with patched_llm_settings(llm_base_url="http://localhost:8080"):
            with patch.object(RemoteLlamaBackend, "chat", return_value="remote-ok") as remote_chat:
                with patch.object(OpenAIPaidBackend, "chat", side_effect=AssertionError("paid should not be used")):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "remote-ok")
                    remote_chat.assert_called()

    def test_generate_chat_force_paid_only_skips_remote_when_configured(self):
        LLMService._instance = None
        llm = LLMService.get_instance()
        llm.settings.llm_base_url = "http://localhost:8080"
        llm.settings.ai_report_api_key = "test-key"
        llm.settings.ai_report_model = "gpt-5.2"

        with (
            patch.object(llm.backend, "chat", side_effect=AssertionError("remote should not be used")),
            patch.object(llm.paid_backend, "chat", return_value="paid-ok") as paid_chat,
        ):
            out = llm.generate_chat(
                [{"role": "user", "content": "hi"}],
                force_paid_only=True,
                stop=["STOP"],
            )

        self.assertEqual(out, "paid-ok")
        self.assertTrue(llm.last_used_paid())
        self.assertEqual(llm.last_route(), "paid")
        _, called_kwargs = paid_chat.call_args
        self.assertEqual(called_kwargs.get("model"), "gpt-5.2")
        self.assertEqual(called_kwargs.get("stop"), ["STOP"])

    def test_generate_chat_falls_back_to_paid_on_remote_failure(self):
        LLMService._instance = None
        llm = LLMService.get_instance()
        llm.settings.llm_base_url = "http://localhost:8080"
        llm.settings.ai_report_api_key = "test-key"
        llm.settings.ai_report_fallback_model = "gpt-5.4-mini"

        with (
            patch.object(llm.backend, "chat", return_value=""),
            patch.object(llm.paid_backend, "chat", return_value="paid-ok") as paid_chat,
        ):
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "t2", "strict": True, "schema": {"type": "object"}},
            }
            out = llm.generate_chat(
                [{"role": "user", "content": "hi"}],
                stop=["STOP"],
                seed=9,
                model="openai/gpt-5.1-chat",
                api_key="openrouter-key",
                base_url="https://openrouter.ai/api/v1",
                service_tier="flex",
                response_format=response_format,
            )
            self.assertEqual(out, "paid-ok")
            self.assertIsNone(llm.get_last_error())
            _, called_kwargs = paid_chat.call_args
            self.assertEqual(called_kwargs.get("model"), "openai/gpt-5.1-chat")
            self.assertEqual(called_kwargs.get("api_key"), "openrouter-key")
            self.assertEqual(called_kwargs.get("base_url"), "https://openrouter.ai/api/v1")
            self.assertNotIn("top_k", called_kwargs)

    def test_generate_chat_skips_paid_when_fallback_disabled(self):
        with patched_llm_settings(llm_base_url="http://localhost:8080"):
            with patch.object(RemoteLlamaBackend, "chat", return_value=""):
                with patch.object(OpenAIPaidBackend, "chat", side_effect=AssertionError("paid should not be used")):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat(
                        [{"role": "user", "content": "hi"}],
                        allow_paid_fallback=False,
                    )
                    self.assertEqual(out, "")
                    self.assertEqual(llm.last_route(), "remote_failed_paid_disabled")

    def test_generate_chat_sets_route_remote_failed_no_paid(self):
        with patched_llm_settings(llm_base_url="http://localhost:8080", ai_report_api_key=None):
            with patch.object(RemoteLlamaBackend, "chat", return_value=""):
                llm = LLMService.get_instance()
                out = llm.generate_chat([{"role": "user", "content": "hi"}])
                self.assertEqual(out, "")
                self.assertEqual(llm.last_route(), "remote_failed_no_paid")

    def test_generate_chat_sets_route_paid_failed_when_paid_attempt_fails(self):
        with patched_llm_settings(llm_base_url="http://localhost:8080"):
            with patch.object(RemoteLlamaBackend, "chat", return_value=""):
                with patch.object(OpenAIPaidBackend, "chat", return_value=""):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "")
                    self.assertEqual(llm.last_route(), "paid_failed")

    def test_no_backend_configured_returns_empty_and_sets_error(self):
        with patched_llm_settings(ai_report_api_key=None):
            llm = LLMService.get_instance()
            out = llm.generate_chat([{"role": "user", "content": "hi"}])
            self.assertEqual(out, "")
            self.assertIn("No LLM backend configured", llm.get_last_error())
            self.assertEqual(llm.last_route(), "no_backend")

    def test_llm_service_reset_context_uses_remote_backend(self):
        with patched_llm_settings(
            llm_base_url="http://localhost:8080",
            ai_report_api_key=None,
            ai_report_base_url=None,
            ai_report_model=None,
            ai_report_fallback_model=None,
        ):
            with patch.object(RemoteLlamaBackend, "reset_context", return_value=True) as reset_mock:
                llm = LLMService.get_instance()
                self.assertTrue(llm.reset_context())
                reset_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
