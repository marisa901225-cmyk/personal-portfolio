import sqlite3
import os
import sys

# 프로젝트 루트(backend 디렉토리) 경로 계산
# backend/scripts/migrations/add_league_column.py -> backend
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")

def migrate():
    print(f"🔍 Searching for database at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 컬럼 추가
    columns = [
        ("league_tag", "VARCHAR(50)"),
        ("is_international", "INTEGER DEFAULT 0")
    ]
    
    for col_name, col_type in columns:
        try:
            cursor.execute(f"ALTER TABLE game_news ADD COLUMN {col_name} {col_type}")
            print(f"✅ Added column: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"ℹ️ Column already exists: {col_name}")
            else:
                print(f"❌ Failed to add column {col_name}: {e}")
        
    conn.commit()
    conn.close()
    print("🚀 Migration completed.")

if __name__ == "__main__":
    migrate()
