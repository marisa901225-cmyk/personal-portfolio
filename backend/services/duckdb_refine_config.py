from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db"


def get_db_path() -> str:
    """Return the path to the SQLite database file."""
    return os.environ.get("DATABASE_PATH", str(_DEFAULT_DB_PATH))
