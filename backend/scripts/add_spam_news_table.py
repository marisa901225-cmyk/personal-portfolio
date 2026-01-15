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
                rule_version INTEGER DEFAULT 1,
                is_restored INTEGER DEFAULT 0,
                restored_at DATETIME,
                restored_reason VARCHAR(200),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_id ON spam_news (id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_content_hash ON spam_news (content_hash)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_created_at ON spam_news (created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_spam_reason ON spam_news (spam_reason)")

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
