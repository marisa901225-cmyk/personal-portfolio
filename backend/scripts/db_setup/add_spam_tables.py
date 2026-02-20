"""
Spam 테이블(spam_alarms, spam_news) 생성을 위한 통합 마이그레이션 스크립트

사용법:
    python -m backend.scripts.db_setup.add_spam_tables          # 모든 테이블 생성
    python -m backend.scripts.db_setup.add_spam_tables --table alarms  # spam_alarms만
    python -m backend.scripts.db_setup.add_spam_tables --table news    # spam_news만
"""
import argparse
import os
import sqlite3
from typing import Optional, List


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")


def resolve_db_path(cli_db_path: Optional[str]) -> str:
    return cli_db_path or os.getenv("PORTFOLIO_DB_PATH") or DEFAULT_DB_PATH


def create_spam_alarms_table(cursor: sqlite3.Cursor) -> None:
    """spam_alarms 테이블 생성"""
    print("  Creating spam_alarms table...")
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
            rule_version INTEGER DEFAULT 1,
            is_restored INTEGER DEFAULT 0,
            restored_at DATETIME,
            restored_reason VARCHAR(200),
            received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_id ON spam_alarms (id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_created_at ON spam_alarms (created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_classification ON spam_alarms (classification)")
    print("  ✓ spam_alarms table created.")


def create_spam_news_table(cursor: sqlite3.Cursor) -> None:
    """spam_news 테이블 생성"""
    print("  Creating spam_news table...")
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
    print("  ✓ spam_news table created.")


def run_migration(db_path: str, tables: List[str]) -> int:
    if not os.path.exists(db_path):
        print(f"Error: DB file not found at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print(f"Running spam tables migration in: {db_path}")
        
        if "alarms" in tables or "all" in tables:
            create_spam_alarms_table(cursor)
        
        if "news" in tables or "all" in tables:
            create_spam_news_table(cursor)

        conn.commit()
        print("Migration completed successfully. ✓")
        return 0
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create spam tables (spam_alarms, spam_news) in SQLite"
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH}; can also use PORTFOLIO_DB_PATH env)",
    )
    parser.add_argument(
        "--table",
        choices=["alarms", "news", "all"],
        default="all",
        help="Which table(s) to create: alarms, news, or all (default: all)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(args.db_path)
    tables = [args.table] if args.table != "all" else ["all"]
    return run_migration(db_path, tables)


if __name__ == "__main__":
    raise SystemExit(main())
