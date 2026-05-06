import unittest
from unittest.mock import patch

from backend.services.translation_rag import (
    GlossaryEntry,
    apply_glossary_repairs,
    build_translation_messages,
    build_translation_batch_requests,
    select_glossary_entries,
    submit_translation_batch,
    split_text_into_chunks,
)


class TranslationRagTests(unittest.TestCase):
    def test_split_text_into_chunks_keeps_paragraph_boundaries(self) -> None:
        text = "A" * 20 + "\n\n" + "B" * 20 + "\n\n" + "C" * 20
        chunks = split_text_into_chunks(text, max_chars=45)
        self.assertEqual(chunks, [("A" * 20) + "\n\n" + ("B" * 20), "C" * 20])

    def test_select_glossary_entries_prefers_matching_terms(self) -> None:
        glossary = [
            GlossaryEntry(source="ムジーク卿", target="무지크 경"),
            GlossaryEntry(source="聖杯戦争", target="성배전쟁"),
            GlossaryEntry(source="関係없는用語", target="무관한 용어"),
        ]
        selected = select_glossary_entries("ムジーク卿と聖杯戦争の話だ。", glossary)
        self.assertEqual([entry.source for entry in selected], ["ムジーク卿", "聖杯戦争"])

    def test_build_translation_messages_includes_glossary_and_context(self) -> None:
        messages = build_translation_messages(
            "今日はいい天気ですね。",
            glossary_entries=[GlossaryEntry(source="天気", target="날씨", note="일반 명사")],
            previous_translations=["이전 번역 문장."],
        )
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("天気 -> 날씨", messages[0]["content"])
        self.assertIn("이전 번역 문장.", messages[1]["content"])

    def test_apply_glossary_repairs_rewrites_common_mistakes(self) -> None:
        text = "무직경이 호문쿨스와 마법 회로를 언급했다."
        entries = [
            GlossaryEntry(source="ムジーク卿", target="무지크 경", repairs=("무직경",)),
            GlossaryEntry(source="ホムンクルス", target="호문쿨루스", repairs=("호문쿨스",)),
            GlossaryEntry(source="魔術回路", target="마술회로", repairs=("마법 회로",)),
        ]
        repaired = apply_glossary_repairs(text, entries)
        self.assertEqual(repaired, "무지크 경이 호문쿨루스와 마술회로를 언급했다.")

    def test_build_translation_batch_requests_keys_chunks_and_source_context(self) -> None:
        requests = build_translation_batch_requests(
            ["ムジーク卿が来た。", "聖杯戦争が始まる。"],
            glossary=[
                GlossaryEntry(source="ムジーク卿", target="무지크 경"),
                GlossaryEntry(source="聖杯戦争", target="성배전쟁"),
            ],
            max_tokens=1234,
            temperature=0.1,
        )

        self.assertEqual([request.key for request in requests], ["chunk-00000", "chunk-00001"])
        self.assertEqual(requests[0].max_tokens, 1234)
        self.assertEqual(requests[0].temperature, 0.1)
        self.assertIn("ムジーク卿 -> 무지크 경", requests[0].messages[0]["content"])
        self.assertIn("Previous Japanese source context", requests[1].messages[1]["content"])

    def test_submit_translation_batch_uses_llm_batch_route(self) -> None:
        class FakeLLM:
            settings = type(
                "Settings",
                (),
                {
                    "translation_batch_max_tokens": 2222,
                    "translation_batch_temperature": 0.15,
                },
            )()

            def __init__(self) -> None:
                self.calls = []

            def submit_batch(self, requests, **kwargs):
                self.calls.append((requests, kwargs))
                return {"id": "batch-1"}

        fake = FakeLLM()
        with patch("backend.services.llm.service.LLMService.get_instance", return_value=fake):
            out = submit_translation_batch(["今日はいい天気ですね。"], provider="openai", model="gpt-5.2")

        self.assertEqual(out, {"id": "batch-1"})
        requests, kwargs = fake.calls[0]
        self.assertEqual(requests[0].max_tokens, 2222)
        self.assertEqual(requests[0].temperature, 0.15)
        self.assertEqual(kwargs["provider"], "openai")
        self.assertEqual(kwargs["model"], "gpt-5.2")


if __name__ == "__main__":
    unittest.main()
