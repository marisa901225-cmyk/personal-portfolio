"""Backwards-compatible wrappers around the canonical news dedup helpers."""

from functools import lru_cache
from typing import Iterable

from .core import _normalize_text as normalize_news_text
from .core import calculate_simhash


def _normalize_text(text: str) -> str:
    return normalize_news_text(text)


@lru_cache(maxsize=2048)
def compute_simhash_for_text(text: str) -> int:
    """
    Keep the legacy int-returning API, but delegate hashing to the shared core logic.
    """
    return int(calculate_simhash(text))


def is_duplicate(text: str, existing_hashes: Iterable[int | str]) -> bool:
    """
    Check if the given text is a duplicate based on existing hashes.
    Accepts either legacy int hashes or newer string hashes.
    """
    computed_hash = compute_simhash_for_text(text)
    normalized_hashes = {int(value) for value in existing_hashes}
    return computed_hash in normalized_hashes
