import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.llm.backends.remote import RemoteLlamaBackend


class TestRemoteLlamaBackend(unittest.TestCase):
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

    def test_remote_backend_consumes_context_tokens_from_timings(self):
        settings = SimpleNamespace(
            llm_base_url="http://default-server:8080",
            llm_api_key=None,
            llm_timeout=30,
        )
        backend = RemoteLlamaBackend(settings)

        try:
            with patch.object(backend, "_get_model_id", return_value="gemma-test"):
                with patch.object(
                    backend,
                    "_request_json_with_retries",
                    return_value={
                        "choices": [{"message": {"content": "ok"}}],
                        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
                        "timings": {"cache_n": 900, "prompt_n": 120, "predicted_n": 30},
                    },
                ):
                    out = backend.chat([{"role": "user", "content": "hi"}])

            self.assertEqual(out, "ok")
            self.assertEqual(
                backend.consume_last_token_metrics(),
                {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                    "context_tokens": 1050,
                },
            )
            self.assertIsNone(backend.consume_last_token_metrics())
        finally:
            backend.close()

    def test_remote_backend_chat_uses_gpu_work_lock(self):
        settings = SimpleNamespace(
            llm_base_url="http://default-server:8080",
            llm_api_key=None,
            llm_timeout=30,
        )
        backend = RemoteLlamaBackend(settings)
        labels: list[str] = []

        @contextmanager
        def recording_lock(label: str):
            labels.append(label)
            yield

        try:
            with (
                patch.object(backend, "_get_model_id", return_value="gemma-test"),
                patch(
                    "backend.services.llm.backends.remote.gpu_heavy_work_lock",
                    side_effect=recording_lock,
                ),
                patch.object(
                    backend,
                    "_request_json_with_retries",
                    return_value={"choices": [{"message": {"content": "ok"}}]},
                ),
            ):
                out = backend.chat([{"role": "user", "content": "hi"}])

            self.assertEqual(out, "ok")
            self.assertEqual(labels, ["remote_llm_chat"])
        finally:
            backend.close()


if __name__ == "__main__":
    unittest.main()
