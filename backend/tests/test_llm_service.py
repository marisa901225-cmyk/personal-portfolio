# backend/tests/test_llm_service.py
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.llm.service import LLMService
from backend.services.llm.config import Settings
from backend.services.llm.backends.remote import RemoteLlamaBackend
from backend.services.llm.backends.paid import OpenAIPaidBackend


class TestLLMService(unittest.TestCase):
    def tearDown(self):
        LLMService._instance = None

    def test_generate_chat_uses_paid_when_remote_not_configured(self):
        # We need to mock the global settings used by LLMService
        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = None
            mock_settings.ai_report_api_key = "test-key"
            mock_settings.ai_report_base_url = "https://api.openai.com/v1"
            mock_settings.ai_report_model = "gpt-5.2"
            mock_settings.ai_report_fallback_model = "gpt-5-nano"

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
        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = "http://localhost:8080"
            mock_settings.ai_report_api_key = "test-key"

            with patch.object(RemoteLlamaBackend, "chat", return_value="remote-ok") as remote_chat:
                with patch.object(OpenAIPaidBackend, "chat", side_effect=AssertionError("paid should not be used")):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "remote-ok")
                    remote_chat.assert_called()

    def test_generate_chat_falls_back_to_paid_on_remote_failure(self):
        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = "http://localhost:8080"
            mock_settings.ai_report_api_key = "test-key"
            mock_settings.ai_report_fallback_model = "gpt-5-nano"

            def _remote_fail(*args, **kwargs):
                return ""

            with patch.object(RemoteLlamaBackend, "chat", new=_remote_fail):
                with patch.object(OpenAIPaidBackend, "chat", return_value="paid-ok") as paid_chat:
                    llm = LLMService.get_instance()
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
        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = "http://localhost:8080"
            mock_settings.ai_report_api_key = "test-key"

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
        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = "http://localhost:8080"
            mock_settings.ai_report_api_key = None

            with patch.object(RemoteLlamaBackend, "chat", return_value=""):
                llm = LLMService.get_instance()
                out = llm.generate_chat([{"role": "user", "content": "hi"}])
                self.assertEqual(out, "")
                self.assertEqual(llm.last_route(), "remote_failed_no_paid")

    def test_generate_chat_sets_route_paid_failed_when_paid_attempt_fails(self):
        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = "http://localhost:8080"
            mock_settings.ai_report_api_key = "test-key"

            with patch.object(RemoteLlamaBackend, "chat", return_value=""):
                with patch.object(OpenAIPaidBackend, "chat", return_value=""):
                    llm = LLMService.get_instance()
                    out = llm.generate_chat([{"role": "user", "content": "hi"}])
                    self.assertEqual(out, "")
                    self.assertEqual(llm.last_route(), "paid_failed")

    def test_no_backend_configured_returns_empty_and_sets_error(self):
        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = None
            mock_settings.ai_report_api_key = None
            
            llm = LLMService.get_instance()
            out = llm.generate_chat([{"role": "user", "content": "hi"}])
            self.assertEqual(out, "")
            self.assertIn("No LLM backend configured", llm.get_last_error())
            self.assertEqual(llm.last_route(), "no_backend")

    def test_paid_backend_falls_back_to_responses_when_chat_completions_not_supported(self):
        class _Resp:
            def __init__(self, status_code: int, json_data=None, text: str = ""):
                self.status_code = status_code
                self._json_data = json_data
                self.text = text

            def json(self):
                if isinstance(self._json_data, Exception):
                    raise self._json_data
                return self._json_data

        error_resp = _Resp(
            400,
            json_data={
                "error": {
                    "message": "This model does not support the v1/chat/completions endpoint. Use /responses instead."
                }
            },
        )
        ok_resp = _Resp(200, json_data={"output_text": "responses-ok"})

        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = None
            mock_settings.llm_api_key = None
            mock_settings.llm_timeout = 30
            mock_settings.open_api_key = None
            mock_settings.ai_report_api_key = "test-key"
            mock_settings.ai_report_base_url = "https://api.openai.com/v1"
            mock_settings.ai_report_model = "gpt-5.2"
            mock_settings.ai_report_fallback_model = "gpt-5-nano"
            mock_settings.ai_report_timeout_sec = 30

            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[error_resp, ok_resp])

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5.2",
                stop=["STOP"],
                seed=123,
            )
            self.assertEqual(out, "responses-ok")
            self.assertIsNone(backend.get_last_error())

            # stop/seed가 Chat Completions에는 전달되고, Responses에는 stop이 빠지는지 확인
            first_payload = backend._post.call_args_list[0].kwargs["payload"]
            second_payload = backend._post.call_args_list[1].kwargs["payload"]
            self.assertEqual(first_payload.get("stop"), ["STOP"])
            self.assertEqual(first_payload.get("seed"), 123)
            self.assertEqual(second_payload.get("seed"), 123)
            self.assertIsNone(second_payload.get("stop"))

    def test_paid_backend_falls_back_to_responses_when_chat_content_empty(self):
        class _Resp:
            def __init__(self, status_code: int, json_data=None, text: str = ""):
                self.status_code = status_code
                self._json_data = json_data
                self.text = text

            def json(self):
                if isinstance(self._json_data, Exception):
                    raise self._json_data
                return self._json_data

        chat_ok_but_empty = _Resp(
            200,
            json_data={
                "service_tier": "default",
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": ""},
                    }
                ],
                "usage": {
                    "completion_tokens_details": {
                        "reasoning_tokens": 512
                    }
                },
            },
        )
        responses_ok = _Resp(
            200,
            json_data={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "responses-from-empty-chat"}
                        ],
                    }
                ]
            },
        )

        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = None
            mock_settings.llm_api_key = None
            mock_settings.llm_timeout = 30
            mock_settings.open_api_key = None
            mock_settings.ai_report_api_key = "test-key"
            mock_settings.ai_report_base_url = "https://api.openai.com/v1"
            mock_settings.ai_report_model = "gpt-5-nano"
            mock_settings.ai_report_fallback_model = "gpt-5-nano"
            mock_settings.ai_report_timeout_sec = 30

            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[chat_ok_but_empty, responses_ok])

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5-nano",
            )
            self.assertEqual(out, "responses-from-empty-chat")
            self.assertIsNone(backend.get_last_error())

            second_payload = backend._post.call_args_list[1].kwargs["payload"]
            self.assertEqual(second_payload.get("reasoning"), {"effort": "minimal"})

    def test_paid_backend_clamps_responses_max_output_tokens_minimum(self):
        class _Resp:
            def __init__(self, status_code: int, json_data=None, text: str = ""):
                self.status_code = status_code
                self._json_data = json_data
                self.text = text

            def json(self):
                if isinstance(self._json_data, Exception):
                    raise self._json_data
                return self._json_data

        chat_ok_but_empty = _Resp(
            200,
            json_data={"choices": [{"message": {"content": ""}}]},
        )
        responses_ok = _Resp(200, json_data={"output_text": "ok"})

        with patch("backend.services.llm.config.settings") as mock_settings:
            mock_settings.llm_base_url = None
            mock_settings.llm_api_key = None
            mock_settings.llm_timeout = 30
            mock_settings.open_api_key = None
            mock_settings.ai_report_api_key = "test-key"
            mock_settings.ai_report_base_url = "https://api.openai.com/v1"
            mock_settings.ai_report_model = "gpt-5-nano"
            mock_settings.ai_report_fallback_model = "gpt-5-nano"
            mock_settings.ai_report_timeout_sec = 30

            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[chat_ok_but_empty, responses_ok])

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5-nano",
                max_tokens=12,
            )

            self.assertEqual(out, "ok")
            second_payload = backend._post.call_args_list[1].kwargs["payload"]
            self.assertEqual(second_payload.get("max_output_tokens"), 16)

    def test_remote_backend_caches_model_ids_per_base_url(self):
        settings = SimpleNamespace(
            llm_base_url="http://default-server:8080",
            llm_api_key=None,
            llm_timeout=30,
        )
        backend = RemoteLlamaBackend(settings)

        try:
            with patch.object(
                backend,
                "_request_json_with_retries",
                side_effect=[
                    {"data": [{"id": "openvino-model"}]},
                    {"data": [{"id": "vulkan-model"}]},
                ],
            ) as mock_request:
                first = backend._get_model_id("http://openvino-server:8082")
                second = backend._get_model_id("http://llama-server-vulkan-huihui:8083")
                cached = backend._get_model_id("http://openvino-server:8082")

            self.assertEqual(first, "openvino-model")
            self.assertEqual(second, "vulkan-model")
            self.assertEqual(cached, "openvino-model")
            self.assertEqual(mock_request.call_count, 2)
            self.assertEqual(
                mock_request.call_args_list[0].args,
                ("GET", "http://openvino-server:8082/v1/models"),
            )
            self.assertEqual(
                mock_request.call_args_list[1].args,
                ("GET", "http://llama-server-vulkan-huihui:8083/v1/models"),
            )
        finally:
            backend.close()


if __name__ == "__main__":
    unittest.main()
