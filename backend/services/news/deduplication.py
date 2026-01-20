# backend/services/news/deduplication.py
from functools import lru_cache
from typing import Tuple

def _normalize_text(text: str) -> str:
    return ' '.join(text.split()).strip().lower()

@lru_cache(maxsize=2048)
def compute_simhash_for_text(text: str) -> int:
    """
    Compute a simhash for the given text.
    Uses Python's built-in hash for caching demonstration;
    a real implementation would use a proper simhash algorithm.
    """
    norm = _normalize_text(text)
    return hash(norm)

def is_duplicate(text: str, existing_hashes: Tuple[int, ...]) -> bool:
    """
    Check if the given text is a duplicate based on existing hashes.
    """
    h = compute_simhash_for_text(text)
    return h in existing_hashes
