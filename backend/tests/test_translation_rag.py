import unittest

from backend.services.translation_rag import (
    GlossaryEntry,
    apply_glossary_repairs,
    build_translation_messages,
    select_glossary_entries,
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


if __name__ == "__main__":
    unittest.main()
