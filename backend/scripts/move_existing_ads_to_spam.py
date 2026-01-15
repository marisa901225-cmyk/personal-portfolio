# Replace the entire file: backend/scripts/move_existing_ads_to_spam.py
"""
GameNews 테이블의 기존 광고성 데이터를 SpamNews로 이동시키는 스크립트
"""
import argparse
import os
import sqlite3
from datetime import datetime
from typing import Optional


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")

AD_KEYWORDS = ["이벤트", "세미나", "기획전", "가이드북", "서포터즈", "참가자 모집", "수강생 모집"]


def resolve_db_path(cli_db_path: Optional[str]) -> str:
    return cli_db_path or os.getenv("PORTFOLIO_DB_PATH") or DEFAULT_DB_PATH


def move_ads(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"Error: DB file not found at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        query_parts = ["title LIKE ?"] * len(AD_KEYWORDS)
        where_clause = " OR ".join(query_parts)
        params = [f"%{kw}%" for kw in AD_KEYWORDS]

        cursor.execute(
            f"SELECT * FROM game_news WHERE source_type = 'news' AND ({where_clause})",
            params,
        )
        rows = cursor.fetchall()

        if not rows:
            print("No ads found in GameNews.")
            return 0

        print(f"Found {len(rows)} potential ads. Moving to spam_news...")

        moved_count = 0
        for row in rows:
            reason = next((kw for kw in AD_KEYWORDS if kw in row["title"]), "Unknown")

            cursor.execute(
                """
                INSERT INTO spam_news (
                    content_hash, game_tag, category_tag, is_international,
                    event_time, source_type, source_name, title, url,
                    full_content, summary, published_at, spam_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["content_hash"],
                    row["game_tag"],
                    row["category_tag"],
                    row["is_international"],
                    row["event_time"],
                    row["source_type"],
                    row["source_name"],
                    row["title"],
                    row["url"],
                    row["full_content"],
                    row["summary"],
                    row["published_at"],
                    f"Migration: {reason}",
                    row["created_at"],
                    datetime.now().isoformat(),
                ),
            )

            cursor.execute("DELETE FROM game_news WHERE id = ?", (row["id"],))
            moved_count += 1

        conn.commit()
        print(f"Successfully moved {moved_count} articles to spam_news.")
        return 0
    except Exception as e:
        print(f"Failed to move ads: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Move existing ad-like game_news rows to spam_news (SQLite)")
    parser.add_argument(
        "--db-path",
        default=None,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH}; can also use PORTFOLIO_DB_PATH env)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(args.db_path)
    return move_ads(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
