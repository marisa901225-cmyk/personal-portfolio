"""
Spam 관련 테이블 고도화를 위한 스키마 변경 및 인덱스 생성 스크립트
"""
import sqlite3
import os

DB_PATH = "backend/storage/db/portfolio.db"

def evolve_db():
    if not os.path.exists(DB_PATH):
        print(f"Error: DB file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1. SpamNews 테이블 컬럼 추가
        print("Evolving spam_news table...")
        columns_to_add = [
            ("rule_version", "INTEGER DEFAULT 1"),
            ("is_restored", "INTEGER DEFAULT 0"),
            ("restored_at", "DATETIME"),
            ("restored_reason", "VARCHAR(200)")
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
    except Exception as e:
        print(f"DB evolution failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    evolve_db()
