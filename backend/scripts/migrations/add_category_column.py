import sqlite3
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")

def migrate():
    print(f"🔍 Migration: Adding category_tag to {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE game_news ADD COLUMN category_tag VARCHAR(50)")
        print("✅ Added column: category_tag")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("ℹ️ Column already exists: category_tag")
        else:
            print(f"❌ Failed to add column: {e}")
        
    conn.commit()
    conn.close()
    print("🚀 Migration completed.")

if __name__ == "__main__":
    migrate()
