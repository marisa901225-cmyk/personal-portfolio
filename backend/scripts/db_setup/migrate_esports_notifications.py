
import sqlite3
import os
from pathlib import Path

def migrate():
    db_path = "/home/dlckdgn/personal-portfolio/backend/storage/db/portfolio.db"
    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return

    print(f"Migrating database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Add columns if they don't exist
        columns_to_add = [
            ("start_notified_at", "DATETIME"),
            ("imminent_notified_at", "DATETIME")
        ]

        for col_name, col_type in columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE esports_matches ADD COLUMN {col_name} {col_type}")
                print(f"Added column: {col_name}")
            except sqlite3.OperationalError as e:
                if "duplicate column name" in str(e).lower():
                    print(f"Column {col_name} already exists.")
                else:
                    raise e
        
        conn.commit()
        print("Migration completed successfully.")
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
