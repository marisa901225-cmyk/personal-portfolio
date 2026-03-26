import unittest
from unittest.mock import patch

from fastapi import HTTPException

import backend.openvino_server.app as ov_app


class _FakeIds:
    def __init__(self, ids):
        self.ids = ids
        self.shape = (1, len(ids))


class _FakeTokenizer:
    def __init__(self, decoded_text: str):
        self.decoded_text = decoded_text
        self.template_kwargs = None

    def apply_chat_template(self, raw, tokenize=False, add_generation_prompt=False, **kwargs):
        self.template_kwargs = kwargs
        return "PROMPT"

    def __call__(self, prompt, return_tensors="pt"):
        return {"input_ids": _FakeIds([1, 2, 3])}

    def decode(self, token_ids, skip_special_tokens=True):
        return self.decoded_text


class _FakeModel:
    def __init__(self, output_ids):
        self.output_ids = output_ids
        self.last_generate_kwargs = None

    def generate(self, **kwargs):
        self.last_generate_kwargs = kwargs
        return [self.output_ids]


class OpenVinoServerApiTests(unittest.TestCase):
    def test_finish_reason_length_when_max_tokens_reached(self):
        tokenizer = _FakeTokenizer("테스트")
        model = _FakeModel([1, 2, 3, 10, 11, 12])  # completion_tokens=3

        with patch.object(ov_app, "_ensure_loaded", return_value=(tokenizer, model)):
            req = ov_app.ChatCompletionRequest(
                messages=[ov_app.ChatMessage(role="user", content="hi")],
                max_tokens=3,
                temperature=0.0,
            )
            data = ov_app.chat_completions(req)

        self.assertEqual(data["usage"]["completion_tokens"], 3)
        self.assertEqual(data["choices"][0]["finish_reason"], "length")

    def test_stop_sequence_trims_output_and_sets_stop_reason(self):
        tokenizer = _FakeTokenizer("첫 문장 END 이후 문장")
        model = _FakeModel([1, 2, 3, 10, 11])  # completion_tokens=2 (< max_tokens)

        with patch.object(ov_app, "_ensure_loaded", return_value=(tokenizer, model)):
            req = ov_app.ChatCompletionRequest(
                messages=[ov_app.ChatMessage(role="user", content="hi")],
                max_tokens=10,
                stop=["END"],
            )
            data = ov_app.chat_completions(req)

        self.assertEqual(data["choices"][0]["message"]["content"], "첫 문장 ")
        self.assertEqual(data["choices"][0]["finish_reason"], "stop")

    def test_chat_template_kwargs_are_forwarded(self):
        tokenizer = _FakeTokenizer("응답")
        model = _FakeModel([1, 2, 3, 10])

        with patch.object(ov_app, "_ensure_loaded", return_value=(tokenizer, model)):
            req = ov_app.ChatCompletionRequest(
                messages=[ov_app.ChatMessage(role="user", content="hi")],
                max_tokens=5,
                chat_template_kwargs={"enable_thinking": False},
            )
            ov_app.chat_completions(req)

        self.assertIsNotNone(tokenizer.template_kwargs)
        self.assertIn("enable_thinking", tokenizer.template_kwargs)
        self.assertFalse(tokenizer.template_kwargs["enable_thinking"])

    def test_stream_true_returns_400(self):
        req = ov_app.ChatCompletionRequest(
            messages=[ov_app.ChatMessage(role="user", content="hi")],
            max_tokens=10,
            stream=True,
        )

        with self.assertRaises(HTTPException) as ctx:
            ov_app.chat_completions(req)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not supported", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
