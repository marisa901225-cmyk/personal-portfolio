from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class GlossaryEntry:
    source: str
    target: str
    note: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    repairs: tuple[str, ...] = field(default_factory=tuple)


def split_text_into_chunks(text: str, max_chars: int = 1800) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars or not current:
            current = candidate
            continue

        chunks.append(current)
        current = paragraph

    if current:
        chunks.append(current)

    return chunks


def load_glossary(path: str | Path) -> list[GlossaryEntry]:
    raw_items = json.loads(Path(path).read_text(encoding="utf-8"))
    entries: list[GlossaryEntry] = []

    for item in raw_items:
        source = str(item["source"]).strip()
        target = str(item["target"]).strip()
        note = str(item.get("note", "")).strip()
        aliases = tuple(
            alias.strip()
            for alias in item.get("aliases", [])
            if isinstance(alias, str) and alias.strip()
        )
        repairs = tuple(
            repair.strip()
            for repair in item.get("repairs", [])
            if isinstance(repair, str) and repair.strip()
        )
        if source and target:
            entries.append(
                GlossaryEntry(
                    source=source,
                    target=target,
                    note=note,
                    aliases=aliases,
                    repairs=repairs,
                )
            )

    return entries


def _iter_entry_terms(entry: GlossaryEntry) -> Iterable[str]:
    yield entry.source
    for alias in entry.aliases:
        yield alias


def select_glossary_entries(
    chunk_text: str,
    glossary: list[GlossaryEntry],
    *,
    limit: int = 12,
) -> list[GlossaryEntry]:
    scored: list[tuple[int, int, GlossaryEntry]] = []

    for entry in glossary:
        hits = 0
        longest_term = 0
        for term in _iter_entry_terms(entry):
            count = chunk_text.count(term)
            if count:
                hits += count
                longest_term = max(longest_term, len(term))

        if hits:
            scored.append((hits, longest_term, entry))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2].source))
    return [entry for _, _, entry in scored[:limit]]


def build_glossary_block(entries: list[GlossaryEntry]) -> str:
    if not entries:
        return ""

    lines = ["Glossary to obey exactly when relevant:"]
    for entry in entries:
        line = f"- {entry.source} -> {entry.target}"
        if entry.note:
            line += f" ({entry.note})"
        lines.append(line)
        if entry.repairs:
            lines.append(f"  Avoid mistaken forms: {', '.join(entry.repairs)}")
    return "\n".join(lines)


def build_glossary_repair_map(entries: list[GlossaryEntry]) -> dict[str, str]:
    repair_map: dict[str, str] = {}
    for entry in entries:
        for repair in entry.repairs:
            repair_map[repair] = entry.target
    return repair_map


def apply_glossary_repairs(text: str, entries: list[GlossaryEntry]) -> str:
    repaired = text
    for wrong, correct in sorted(build_glossary_repair_map(entries).items(), key=lambda item: len(item[0]), reverse=True):
        repaired = repaired.replace(wrong, correct)
    return repaired


def build_translation_messages(
    chunk_text: str,
    *,
    glossary_entries: list[GlossaryEntry] | None = None,
    previous_translations: list[str] | None = None,
    previous_source_chunks: list[str] | None = None,
) -> list[dict[str, str]]:
    glossary_block = build_glossary_block(glossary_entries or [])

    prior_context = ""
    if previous_translations:
        joined = "\n\n".join(previous_translations[-2:])
        prior_context = f"Previous translated context for style/continuity:\n{joined}"
    prior_source = ""
    if previous_source_chunks:
        joined = "\n\n".join(previous_source_chunks[-2:])
        prior_source = f"Previous Japanese source context:\n{joined}"

    system_lines = [
        "You are a Japanese-to-Korean literary translation engine.",
        "Translate the passage into natural Korean webnovel prose.",
        "Preserve names, setting terms, and tone.",
        "Output only the Korean translation.",
        "Do not add notes, explanations, headers, or analysis.",
        "Do not leave any Japanese text, kana, or kanji in the final answer.",
        "Do not paraphrase away named entities or setting terms.",
    ]
    if glossary_block:
        system_lines.append(glossary_block)

    user_parts = [
        "Translate the following Japanese passage into Korean.",
        "Keep proper nouns and worldbuilding terms consistent.",
    ]
    if prior_context:
        user_parts.append(prior_context)
    if prior_source:
        user_parts.append(prior_source)
    user_parts.append("Source passage:")
    user_parts.append(chunk_text)

    return [
        {"role": "system", "content": "\n".join(system_lines)},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
