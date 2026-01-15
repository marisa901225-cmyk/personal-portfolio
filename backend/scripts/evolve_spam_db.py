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
        # 1. SpamNews 테이블 컬럼 추가
        print("Evolving spam_news table...")
        columns_to_add = [
            ("rule_version", "INTEGER DEFAULT 1"),
            ("is_restored", "INTEGER DEFAULT 0"),
            ("restored_at", "DATETIME"),
            ("restored_reason", "VARCHAR(200)"),
        ]

        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE spam_news ADD COLUMN {col_name} {col_type}")
                print(f"  Added column {col_name} to spam_news")
            except sqlite3.OperationalError:
                print(f"  Column {col_name} already exists in spam_news")

        # 2. SpamAlarm 테이블 컬럼 추가
        print("Evolving spam_alarms table...")
        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE spam_alarms ADD COLUMN {col_name} {col_type}")
                print(f"  Added column {col_name} to spam_alarms")
            except sqlite3.OperationalError:
                print(f"  Column {col_name} already exists in spam_alarms")

        # 3. 인덱스 생성
        print("Creating indices...")
        # SpamNews
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_created_at ON spam_news (created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_spam_reason ON spam_news (spam_reason)")

        # SpamAlarm
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_created_at ON spam_alarms (created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_classification ON spam_alarms (classification)")

        # GameNews (운영 조회 최적화용)
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
    parser = argparse.ArgumentParser(description="Evolve spam DB schema (SQLite)")
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
