import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.services.llm.batch import (
    GeminiBatchClient,
    LLMBatchRequest,
    OpenAIBatchClient,
)
from backend.services.llm.service import LLMService


class _Resp:
    def __init__(self, payload=None, text: str = "") -> None:
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


class LLMBatchTests(unittest.TestCase):
    def test_openai_batch_submits_responses_jsonl(self) -> None:
        settings = SimpleNamespace(
            ai_report_api_key="test-key",
            ai_report_base_url="https://api.openai.com/v1",
            ai_report_model="gpt-5.2",
            translation_batch_model=None,
            ai_report_timeout_sec=30,
        )
        client = OpenAIBatchClient(settings)  # type: ignore[arg-type]
        client._post = Mock(side_effect=[_Resp({"id": "file-1"}), _Resp({"id": "batch-1", "status": "validating"})])

        job = client.submit_responses_batch(
            [
                LLMBatchRequest(
                    key="chunk-00000",
                    messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "text"}],
                    max_tokens=777,
                    temperature=0.2,
                )
            ],
            display_name="novel-translation",
        )

        self.assertEqual(job.id, "batch-1")
        upload_kwargs = client._post.call_args_list[0].kwargs
        uploaded = upload_kwargs["files"]["file"][1].read().decode("utf-8")
        row = json.loads(uploaded)
        self.assertEqual(row["custom_id"], "chunk-00000")
        self.assertEqual(row["url"], "/v1/responses")
        self.assertEqual(row["body"]["model"], "gpt-5.2")
        self.assertEqual(row["body"]["max_output_tokens"], 777)

        create_kwargs = client._post.call_args_list[1].kwargs
        self.assertEqual(create_kwargs["json"]["endpoint"], "/v1/responses")
        self.assertEqual(create_kwargs["json"]["completion_window"], "24h")

    def test_openai_batch_parses_response_jsonl(self) -> None:
        text = json.dumps(
            {
                "custom_id": "chunk-00000",
                "response": {"body": {"output_text": "번역문"}},
            },
            ensure_ascii=False,
        )
        self.assertEqual(OpenAIBatchClient.parse_responses_jsonl(text), {"chunk-00000": "번역문"})

    def test_gemini_batch_submits_inline_generate_content(self) -> None:
        settings = SimpleNamespace(
            google_token="gemini-key",
            translation_batch_model=None,
            gemini_batch_base_url="https://generativelanguage.googleapis.com/v1beta",
            ai_report_timeout_sec=30,
        )
        client = GeminiBatchClient(settings)  # type: ignore[arg-type]
        client._post = Mock(return_value=_Resp({"name": "batches/1", "metadata": {"state": "JOB_STATE_PENDING"}}))

        job = client.submit_generate_content_batch(
            [
                LLMBatchRequest(
                    key="chunk-00000",
                    messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "text"}],
                    max_tokens=500,
                    temperature=0.3,
                )
            ],
            model="gemini-2.5-flash",
        )

        self.assertEqual(job.id, "batches/1")
        call = client._post.call_args
        self.assertIn("/models/gemini-2.5-flash:batchGenerateContent", call.args[0])
        payload = call.kwargs["json"]
        request = payload["batch"]["input_config"]["requests"]["requests"][0]
        self.assertEqual(request["metadata"]["key"], "chunk-00000")
        self.assertEqual(request["request"]["system_instruction"]["parts"][0]["text"], "sys")
        self.assertEqual(request["request"]["generation_config"]["max_output_tokens"], 500)

    def test_llm_service_routes_batch_provider(self) -> None:
        service = LLMService.__new__(LLMService)
        service.settings = SimpleNamespace(translation_batch_provider="gemini")
        with patch("backend.services.llm.service.GeminiBatchClient") as gemini_client:
            gemini_client.return_value.submit_generate_content_batch.return_value = "job"
            out = service.submit_batch([LLMBatchRequest(key="k", messages=[])])

        self.assertEqual(out, "job")


if __name__ == "__main__":
    unittest.main()
