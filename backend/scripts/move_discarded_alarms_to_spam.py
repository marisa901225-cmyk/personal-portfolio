"""
IncomingAlarm의 기존 discarded 데이터를 SpamAlarm으로 이동시키는 스크립트
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = "backend/storage/db/portfolio.db"

def move_discarded_alarms():
    if not os.path.exists(DB_PATH):
        print(f"Error: DB file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 1. 대상 찾기
        cursor.execute("SELECT * FROM incoming_alarms WHERE status = 'discarded'")
        rows = cursor.fetchall()
        
        if not rows:
            print("No discarded alarms found in IncomingAlarm.")
            return

        print(f"Found {len(rows)} discarded alarms. Moving to spam_alarms...")

        moved_count = 0
        for row in rows:
            # spam_alarms에 삽입
            cursor.execute("""
                INSERT INTO spam_alarms (
                    raw_text, masked_text, sender, app_name, package,
                    app_title, conversation, classification, discard_reason,
                    received_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["raw_text"], row["masked_text"], row["sender"], row["app_name"], row["package"],
                row["app_title"], row["conversation"], row["classification"], f"Migration from IncomingAlarm",
                row["received_at"], datetime.now().isoformat()
            ))
            
            # incoming_alarms에서 삭제
            cursor.execute("DELETE FROM incoming_alarms WHERE id = ?", (row["id"],))
            moved_count += 1

        conn.commit()
        print(f"Successfully moved {moved_count} alarms to spam_alarms.")
        
    except Exception as e:
        print(f"Failed to move alarms: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    move_discarded_alarms()
