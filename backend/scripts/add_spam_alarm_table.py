"""
SpamAlarm 테이블 생성을 위한 수동 마이그레이션 스크립트
"""
import sqlite3
import os

DB_PATH = "backend/storage/db/portfolio.db"

def run_migration():
    if not os.path.exists(DB_PATH):
        print(f"Error: DB file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("Creating spam_alarms table...")
        cursor.execute("""
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
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_alarms_id ON spam_alarms (id)")
        
        conn.commit()
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
