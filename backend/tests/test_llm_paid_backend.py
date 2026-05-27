import unittest

from backend.services.llm.backends.paid import OpenAIPaidBackend
from backend.services.llm.config import Settings
from backend.tests.llm_test_helpers import FakeResponse, patched_llm_settings


class TestOpenAIPaidBackend(unittest.TestCase):
    def test_paid_backend_falls_back_to_responses_when_chat_completions_not_supported(self):
        error_resp = FakeResponse(
            400,
            json_data={
                "error": {
                    "message": "This model does not support the v1/chat/completions endpoint. Use /responses instead."
                }
            },
        )
        ok_resp = FakeResponse(200, json_data={"output_text": "responses-ok"})

        with patched_llm_settings(ai_report_model="gpt-5.2", ai_report_fallback_model="gpt-5.4-mini"):
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
        first_payload = backend._post.call_args_list[0].kwargs["payload"]
        second_payload = backend._post.call_args_list[1].kwargs["payload"]
        self.assertEqual(first_payload.get("stop"), ["STOP"])
        self.assertEqual(first_payload.get("seed"), 123)
        self.assertEqual(second_payload.get("seed"), 123)
        self.assertIsNone(second_payload.get("stop"))

    def test_paid_backend_falls_back_to_responses_when_chat_content_empty(self):
        chat_ok_but_empty = FakeResponse(
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
        responses_ok = FakeResponse(
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

        with patched_llm_settings():
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[chat_ok_but_empty, responses_ok])

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5.4-mini",
            )

        self.assertEqual(out, "responses-from-empty-chat")
        self.assertIsNone(backend.get_last_error())
        second_payload = backend._post.call_args_list[1].kwargs["payload"]
        self.assertEqual(second_payload.get("reasoning"), {"effort": "medium"})

    def test_paid_backend_clamps_responses_max_output_tokens_minimum(self):
        chat_ok_but_empty = FakeResponse(
            200,
            json_data={"choices": [{"message": {"content": ""}}]},
        )
        responses_ok = FakeResponse(200, json_data={"output_text": "ok"})

        with patched_llm_settings():
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[chat_ok_but_empty, responses_ok])

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5.4-mini",
                max_tokens=12,
            )

        self.assertEqual(out, "ok")
        second_payload = backend._post.call_args_list[1].kwargs["payload"]
        self.assertEqual(second_payload.get("max_output_tokens"), 16)

    def test_paid_backend_retries_responses_when_reasoning_exhausts_output_tokens(self):
        chat_ok_but_empty = FakeResponse(
            200,
            json_data={"choices": [{"message": {"content": ""}}]},
        )
        responses_incomplete = FakeResponse(
            200,
            json_data={
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output": [{"type": "reasoning"}],
                "usage": {"output_tokens": 700, "output_tokens_details": {"reasoning_tokens": 700}},
            },
        )
        responses_ok = FakeResponse(200, json_data={"output_text": "retry-ok"})

        with patched_llm_settings():
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[chat_ok_but_empty, responses_incomplete, responses_ok])

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5.4-mini",
                max_tokens=700,
            )

        self.assertEqual(out, "retry-ok")
        second_payload = backend._post.call_args_list[1].kwargs["payload"]
        third_payload = backend._post.call_args_list[2].kwargs["payload"]
        self.assertEqual(second_payload.get("max_output_tokens"), 2048)
        self.assertEqual(third_payload.get("max_output_tokens"), 2048)

    def test_paid_backend_responses_respects_reasoning_effort_override(self):
        chat_ok_but_empty = FakeResponse(
            200,
            json_data={"choices": [{"message": {"content": ""}}]},
        )
        responses_ok = FakeResponse(
            200,
            json_data={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "title-ok"}],
                    }
                ]
            },
        )

        with patched_llm_settings():
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[chat_ok_but_empty, responses_ok])

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5.4-mini",
                reasoning_effort="none",
            )

        self.assertEqual(out, "title-ok")
        second_payload = backend._post.call_args_list[1].kwargs["payload"]
        self.assertEqual(second_payload.get("reasoning"), {"effort": "none"})

    def test_paid_backend_chat_includes_gpt5_reasoning_effort_override(self):
        with patched_llm_settings():
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(
                return_value=FakeResponse(200, json_data={"choices": [{"message": {"content": "ok"}}]})
            )

            out = backend.chat(
                [{"role": "user", "content": "hi"}],
                model="gpt-5.4-mini",
                reasoning_effort="none",
            )

        self.assertEqual(out, "ok")
        first_payload = backend._post.call_args_list[0].kwargs["payload"]
        self.assertEqual(first_payload.get("reasoning_effort"), "none")

    def test_paid_backend_responses_preserves_multimodal_content(self):
        error_resp = FakeResponse(
            400,
            json_data={
                "error": {
                    "message": "This model does not support the v1/chat/completions endpoint. Use /responses instead."
                }
            },
        )
        ok_resp = FakeResponse(200, json_data={"output_text": "vision-ok"})

        with patched_llm_settings(ai_report_model="gpt-5.4"):
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(side_effect=[error_resp, ok_resp])

            out = backend.chat(
                [
                    {"role": "system", "content": "chart-review-system"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "review this chart"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,AAAA"},
                            },
                        ],
                    },
                ],
                model="gpt-5.4",
            )

        self.assertEqual(out, "vision-ok")
        second_payload = backend._post.call_args_list[1].kwargs["payload"]
        self.assertEqual(
            second_payload["input"][1]["content"],
            [
                {"type": "input_text", "text": "review this chart"},
                {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
            ],
        )

    def test_paid_backend_prepends_gpt5_paid_system_prompt(self):
        response = FakeResponse(
            200,
            json_data={"choices": [{"message": {"content": "ok"}}]},
        )

        with patched_llm_settings():
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(return_value=response)

            out = backend.chat(
                [{"role": "system", "content": "main-system"}, {"role": "user", "content": "hi"}],
                model="gpt-5.4-mini",
                paid_system_prompt="paid-system",
            )

        self.assertEqual(out, "ok")
        payload = backend._post.call_args.kwargs["payload"]
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "paid-system"})
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "hi"})
        self.assertEqual(len(payload["messages"]), 2)

    def test_paid_backend_dedupes_repeated_gpt5_paid_system_prompt_lines(self):
        response = FakeResponse(
            200,
            json_data={"choices": [{"message": {"content": "ok"}}]},
        )

        with patched_llm_settings():
            backend = OpenAIPaidBackend(Settings())
            backend._post = unittest.mock.Mock(return_value=response)

            out = backend.chat(
                [
                    {
                        "role": "system",
                        "content": "main-system\nMaximum 120 words.",
                    },
                    {"role": "user", "content": "hi"},
                ],
                model="gpt-5.4-mini",
                paid_system_prompt="Maximum 120 words.\nUse concise Korean.",
            )

        self.assertEqual(out, "ok")
        payload = backend._post.call_args.kwargs["payload"]
        self.assertEqual(
            payload["messages"][0],
            {"role": "system", "content": "Maximum 120 words.\nUse concise Korean."},
        )
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "hi"})
        self.assertEqual(len(payload["messages"]), 2)


if __name__ == "__main__":
    unittest.main()
