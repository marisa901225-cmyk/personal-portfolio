"""
SpamNews 테이블 생성을 위한 수동 마이그레이션 스크립트
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
        print("Creating spam_news table...")
        cursor.execute("""
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
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_id ON spam_news (id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_spam_news_content_hash ON spam_news (content_hash)")
        
        conn.commit()
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
