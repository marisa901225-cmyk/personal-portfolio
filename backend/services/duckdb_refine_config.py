from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db"
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# Default keywords (fallback)
_DEFAULT_NEWS_KEYWORDS: Dict[str, List[str]] = {
    "tech": ["AI", "인공지능", "반도체", "클라우드"],
    "economy": ["금리", "환율", "주식", "코스피"],
    "esports": ["LCK", "LoL", "T1", "Faker"],
}

_NEWS_KEYWORDS_CACHE: Dict[str, List[str]] | None = None


def get_db_path() -> str:
    """Return the path to the SQLite database file."""
    return os.environ.get("DATABASE_PATH", str(_DEFAULT_DB_PATH))


def get_news_keywords() -> Dict[str, List[str]]:
    """Load news keywords from YAML config or use defaults."""
    global _NEWS_KEYWORDS_CACHE
    
    if _NEWS_KEYWORDS_CACHE is not None:
        return _NEWS_KEYWORDS_CACHE
    
    yaml_path = _CONFIG_DIR / "news_keywords.yaml"
    
    if yaml_path.exists():
        try:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                _NEWS_KEYWORDS_CACHE = yaml.safe_load(f) or _DEFAULT_NEWS_KEYWORDS
            return _NEWS_KEYWORDS_CACHE
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to load news_keywords.yaml: {e}")
    
    _NEWS_KEYWORDS_CACHE = _DEFAULT_NEWS_KEYWORDS
    return _NEWS_KEYWORDS_CACHE


def get_keywords_for_category(category: str) -> List[str]:
    """Get keywords for a specific category."""
    keywords = get_news_keywords()
    return keywords.get(category, [])
