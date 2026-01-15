# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
>
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
>
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
>
> ---
>
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | Standardize DB path handling for spam DB scripts | P2 | ⬜ Pending |
| 2 | PROMPT-002 | Add unit tests for prompt template loader | P2 | ⬜ Pending |
| 3 | PROMPT-003 | Document spam DB scripts usage and safe runbook | P3 | ⬜ Pending |

**Total: 3 prompts** | **Completed: 0** | **Remaining: 3**

---

## 🟡 Priority 2 (High) - Execute First

### [PROMPT-001] Standardize DB path handling for spam DB scripts

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` / `multi_replace_string_in_file` to make changes. Do NOT just show code.**

**Task**: Make the spam DB maintenance scripts robust regardless of the current working directory by using an absolute default DB path, plus a `--db-path` CLI option (and optional `PORTFOLIO_DB_PATH` env override).
**Files to Modify**: `backend/scripts/add_spam_news_table.py`, `backend/scripts/add_spam_alarm_table.py`, `backend/scripts/evolve_spam_db.py`

#### Instructions:

1. Replace the entire contents of each file with the full code shown below.
2. Keep the behavior the same, but make DB path handling explicit and stable.

#### Implementation Code:

```python
# Replace the entire file: backend/scripts/add_spam_news_table.py
"""
SpamNews 테이블 생성을 위한 수동 마이그레이션 스크립트
"""
import argparse
import os
import sqlite3
from typing import Optional


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")


def resolve_db_path(cli_db_path: Optional[str]) -> str:
    return cli_db_path or os.getenv("PORTFOLIO_DB_PATH") or DEFAULT_DB_PATH


def run_migration(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"Error: DB file not found at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print(f"Creating spam_news table in: {db_path}")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS spam_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_hash VARCHAR(64) NOT NULL,
                game_tag VARCHAR(50),
                category_tag VARCHAR(50),
                is_international INTEGER DEFAULT 0,
                event_time DATETIME,
                source_type VARCHAR(20) DEFAULT 'news',
                source_name VARCHAR(50),
                title VARCHAR(300) NOT NULL,
                url VARCHAR(500),
                full_content TEXT NOT NULL,
                summary TEXT,
                published_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                spam_reason VARCHAR(100),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_id ON spam_news (id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_content_hash ON spam_news (content_hash)")

        conn.commit()
        print("Migration completed successfully.")
        return 0
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create spam_news table (SQLite)")
    parser.add_argument(
        "--db-path",
        default=None,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH}; can also use PORTFOLIO_DB_PATH env)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(args.db_path)
    return run_migration(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# Replace the entire file: backend/scripts/add_spam_alarm_table.py
"""
SpamAlarm 테이블 생성을 위한 수동 마이그레이션 스크립트
"""
import argparse
import os
import sqlite3
from typing import Optional


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")


def resolve_db_path(cli_db_path: Optional[str]) -> str:
    return cli_db_path or os.getenv("PORTFOLIO_DB_PATH") or DEFAULT_DB_PATH


def run_migration(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"Error: DB file not found at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print(f"Creating spam_alarms table in: {db_path}")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS spam_alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                masked_text TEXT,
                sender VARCHAR(200),
                app_name VARCHAR(100),
                package VARCHAR(200),
                app_title VARCHAR(200),
                conversation VARCHAR(200),
                classification VARCHAR(20),
                discard_reason VARCHAR(200),
                received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_id ON spam_alarms (id)")

        conn.commit()
        print("Migration completed successfully.")
        return 0
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create spam_alarms table (SQLite)")
    parser.add_argument(
        "--db-path",
        default=None,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH}; can also use PORTFOLIO_DB_PATH env)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(args.db_path)
    return run_migration(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
```

```python
# Replace the entire file: backend/scripts/evolve_spam_db.py
"""
Spam 관련 테이블 고도화를 위한 스키마 변경 및 인덱스 생성 스크립트
"""
import argparse
import os
import sqlite3
from typing import Optional


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")


def resolve_db_path(cli_db_path: Optional[str]) -> str:
    return cli_db_path or os.getenv("PORTFOLIO_DB_PATH") or DEFAULT_DB_PATH


def evolve_db(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"Error: DB file not found at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print(f"Evolving spam tables in: {db_path}")

        columns_to_add = [
            ("rule_version", "INTEGER DEFAULT 1"),
            ("is_restored", "INTEGER DEFAULT 0"),
            ("restored_at", "DATETIME"),
            ("restored_reason", "VARCHAR(200)"),
        ]

        print("Evolving spam_news table...")
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE spam_news ADD COLUMN {col_name} {col_type}")
                print(f"  Added column {col_name} to spam_news")
            except sqlite3.OperationalError:
                print(f"  Column {col_name} already exists in spam_news")

        print("Evolving spam_alarms table...")
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE spam_alarms ADD COLUMN {col_name} {col_type}")
                print(f"  Added column {col_name} to spam_alarms")
            except sqlite3.OperationalError:
                print(f"  Column {col_name} already exists in spam_alarms")

        print("Creating indices...")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_created_at ON spam_news (created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_spam_reason ON spam_news (spam_reason)")

        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_created_at ON spam_alarms (created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_classification ON spam_alarms (classification)")

        cursor.execute("CREATE INDEX IF NOT EXISTS ix_game_news_created_at ON game_news (created_at)")

        conn.commit()
        print("DB evolution completed successfully.")
        return 0
    except Exception as e:
        print(f"DB evolution failed: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evolve spam-related tables (SQLite)")
    parser.add_argument(
        "--db-path",
        default=None,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH}; can also use PORTFOLIO_DB_PATH env)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(args.db_path)
    return evolve_db(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
```

#### Verification:
- Run: `python3 backend/scripts/add_spam_news_table.py --db-path backend/storage/db/portfolio.db`
- Run: `python3 backend/scripts/add_spam_alarm_table.py --db-path backend/storage/db/portfolio.db`
- Run: `python3 backend/scripts/evolve_spam_db.py --db-path backend/storage/db/portfolio.db`
- Expected: Scripts succeed from any working directory; `--db-path` overrides default; `PORTFOLIO_DB_PATH` also works.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

### [PROMPT-002] Add unit tests for prompt template loader

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `create_file` / `replace_string_in_file` to make changes. Do NOT just show code.**

**Task**: Add `unittest` coverage for `backend/services/prompt_loader.py` to lock in behavior (missing file, variable substitution, missing variables, hot reload via mtime).
**Files to Modify**: `backend/tests/test_prompt_loader.py`

#### Instructions:

1. Create `backend/tests/test_prompt_loader.py` with the full content below.
2. The tests must not depend on any real prompt files in the repo; use a temporary directory.

#### Implementation Code:

```python
# Create this file: backend/tests/test_prompt_loader.py
import os
import tempfile
import unittest

from backend.services import prompt_loader


class TestPromptLoader(unittest.TestCase):
    def setUp(self):
        self._orig_prompts_dir = prompt_loader.PROMPTS_DIR
        prompt_loader._prompt_cache.clear()
        prompt_loader._prompt_mtime.clear()
        self._tmp = tempfile.TemporaryDirectory()
        prompt_loader.PROMPTS_DIR = self._tmp.name

    def tearDown(self):
        prompt_loader.PROMPTS_DIR = self._orig_prompts_dir
        prompt_loader._prompt_cache.clear()
        prompt_loader._prompt_mtime.clear()
        self._tmp.cleanup()

    def _write_prompt(self, name: str, content: str) -> str:
        path = os.path.join(prompt_loader.PROMPTS_DIR, f"{name}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_load_prompt_returns_empty_when_missing(self):
        self.assertEqual(prompt_loader.load_prompt("does_not_exist"), "")

    def test_load_prompt_substitutes_variables(self):
        self._write_prompt("hello", "Hello {name}!")
        rendered = prompt_loader.load_prompt("hello", name="World")
        self.assertEqual(rendered, "Hello World!")

    def test_load_prompt_missing_variable_returns_template(self):
        self._write_prompt("needs_var", "Value={value}")
        rendered = prompt_loader.load_prompt("needs_var")
        self.assertEqual(rendered, "Value={value}")

    def test_load_prompt_hot_reload_on_mtime_change(self):
        path = self._write_prompt("reload", "v1")
        first = prompt_loader.load_prompt("reload")
        self.assertEqual(first, "v1")

        with open(path, "w", encoding="utf-8") as f:
            f.write("v2")
        st = os.stat(path)
        os.utime(path, (st.st_atime, st.st_mtime + 10))

        second = prompt_loader.load_prompt("reload")
        self.assertEqual(second, "v2")


if __name__ == "__main__":
    unittest.main()
```

#### Verification:
- Run: `python3 -m unittest discover backend/tests`
- Expected: All tests pass (including the new `test_prompt_loader.py`).

**✅ After completing this prompt, proceed to [PROMPT-003]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-003] Document spam DB scripts usage and safe runbook

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `create_file` to make changes. Do NOT just show code.**

**Task**: Add a minimal runbook for spam DB scripts so they can be executed safely and reproducibly (DB path, backups, order, verification queries).
**Files to Modify**: `backend/scripts/SPAM_DB_SCRIPTS.md`

#### Instructions:

1. Create `backend/scripts/SPAM_DB_SCRIPTS.md` with the full content below.
2. Do not include any real tokens/credentials.

#### Implementation Code:

```markdown
# Spam DB Scripts Runbook

## DB Path Rules

These scripts operate on the SQLite database file:

- Default: `backend/storage/db/portfolio.db` (resolved to an absolute path based on script location)
- Override via CLI: `--db-path /absolute/or/relative/path/to/portfolio.db`
- Override via env: `PORTFOLIO_DB_PATH=/path/to/portfolio.db`

Recommended: always pass `--db-path` explicitly in production/automation.

---

## Pre-Run Checklist

1. Confirm you are targeting the correct DB file.
2. Take a backup before any schema changes or large moves.
3. Ensure no other process is writing to the DB during migrations (best-effort for SQLite).

Example backup (from repo root):

```bash
cp backend/storage/db/portfolio.db "backend/storage/db/portfolio.db.bak.$(date +%Y%m%d_%H%M%S)"
```

---

## Script Overview (Common)

### Create tables (first-time only)

- `backend/scripts/add_spam_news_table.py`: creates `spam_news`
- `backend/scripts/add_spam_alarm_table.py`: creates `spam_alarms`

Run:

```bash
python3 backend/scripts/add_spam_news_table.py --db-path backend/storage/db/portfolio.db
python3 backend/scripts/add_spam_alarm_table.py --db-path backend/storage/db/portfolio.db
```

### Evolve schema / indices

- `backend/scripts/evolve_spam_db.py`: adds columns + indices for spam tables and some query indices

Run:

```bash
python3 backend/scripts/evolve_spam_db.py --db-path backend/storage/db/portfolio.db
```

### Move existing records to spam tables

These scripts depend on your current schema and data. Always run a backup first:

- `backend/scripts/move_existing_ads_to_spam.py`
- `backend/scripts/move_discarded_alarms_to_spam.py`

Tip: review the script source to confirm the selection criteria before running.

---

## Recommended Execution Order (Safe Default)

1. Backup DB
2. Create spam tables (if not present)
3. Evolve spam schema/indices
4. Run any move/backfill scripts (one by one)
5. Verify row counts and spot-check samples

---

## Verification Queries (SQLite)

You can verify expected state with a SQLite client:

```sql
-- Tables exist
SELECT name FROM sqlite_master WHERE type='table' AND name IN ('spam_news', 'spam_alarms');

-- Columns exist (example)
PRAGMA table_info(spam_news);
PRAGMA table_info(spam_alarms);

-- Indices exist (example)
PRAGMA index_list(spam_news);
PRAGMA index_list(spam_alarms);

-- Basic row counts
SELECT COUNT(*) AS spam_news_count FROM spam_news;
SELECT COUNT(*) AS spam_alarms_count FROM spam_alarms;
```

---

## Rollback Notes

SQLite schema changes (e.g., `ALTER TABLE ADD COLUMN`) are not easily reversible.
If something goes wrong, restore from your backup file.
```

#### Verification:
- Run: `ls -la backend/scripts/SPAM_DB_SCRIPTS.md`
- Expected: The runbook file exists and contains the DB path rules, pre-run checklist, recommended order, and verification queries.

**🎉 ALL PROMPTS COMPLETED!**
