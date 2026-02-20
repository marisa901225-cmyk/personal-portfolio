# Replace the entire file: backend/scripts/move_discarded_alarms_to_spam.py
"""
IncomingAlarm의 기존 discarded 데이터를 SpamAlarm으로 이동시키는 스크립트
"""
import argparse
import os
import sqlite3
from datetime import datetime
from typing import Optional


BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")


def resolve_db_path(cli_db_path: Optional[str]) -> str:
    return cli_db_path or os.getenv("PORTFOLIO_DB_PATH") or DEFAULT_DB_PATH


def move_discarded_alarms(db_path: str) -> int:
    if not os.path.exists(db_path):
        print(f"Error: DB file not found at {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM incoming_alarms WHERE status = 'discarded'")
        rows = cursor.fetchall()

        if not rows:
            print("No discarded alarms found in IncomingAlarm.")
            return 0

        print(f"Found {len(rows)} discarded alarms. Moving to spam_alarms...")

        moved_count = 0
        for row in rows:
            cursor.execute(
                """
                INSERT INTO spam_alarms (
                    raw_text, masked_text, sender, app_name, package,
                    app_title, conversation, classification, discard_reason,
                    received_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["raw_text"],
                    row["masked_text"],
                    row["sender"],
                    row["app_name"],
                    row["package"],
                    row["app_title"],
                    row["conversation"],
                    row["classification"],
                    "Migration from IncomingAlarm",
                    row["received_at"],
                    datetime.now().isoformat(),
                ),
            )

            cursor.execute("DELETE FROM incoming_alarms WHERE id = ?", (row["id"],))
            moved_count += 1

        conn.commit()
        print(f"Successfully moved {moved_count} alarms to spam_alarms.")
        return 0
    except Exception as e:
        print(f"Failed to move alarms: {e}")
        conn.rollback()
        return 1
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Move discarded incoming alarms to spam_alarms (SQLite)")
    parser.add_argument(
        "--db-path",
        default=None,
        help=f"Path to SQLite DB (default: {DEFAULT_DB_PATH}; can also use PORTFOLIO_DB_PATH env)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    db_path = resolve_db_path(args.db_path)
    return move_discarded_alarms(db_path)


if __name__ == "__main__":
    raise SystemExit(main())
