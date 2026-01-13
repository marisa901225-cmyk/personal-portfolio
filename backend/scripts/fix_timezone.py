import sqlite3
import os
from datetime import datetime, timedelta

def get_db_path():
    return "/home/dlckdgn/personal-portfolio/backend/storage/db/portfolio.db"

def fix_pandascore_timezone():
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Error: Database file not found at {db_path}")
        return

    print(f"Fixing timestamps in {db_path} using sqlite3...")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 1. 대상 레코드 확인
        cursor.execute("SELECT id, event_time FROM game_news WHERE source_name = 'PandaScore' AND source_type = 'schedule'")
        rows = cursor.fetchall()
        print(f"Found {len(rows)} PandaScore schedules to update.")
        
        if not rows:
            print("No records found.")
            return

        # 2. 업데이트 수행
        updated_count = 0
        for row_id, event_time in rows:
            if not event_time:
                continue
            
            try:
                # SQLite의 datetime 함수를 사용하여 직접 업데이트 (+9 hours)
                cursor.execute(
                    "UPDATE game_news SET event_time = datetime(event_time, '+9 hours') WHERE id = ?",
                    (row_id,)
                )
                updated_count += 1
            except Exception as e:
                print(f"Failed to update row {row_id}: {e}")
        
        conn.commit()
        print(f"Successfully updated {updated_count} timestamps.")
        
    except Exception as e:
        print(f"Database error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    fix_pandascore_timezone()
