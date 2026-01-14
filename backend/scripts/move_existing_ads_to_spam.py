"""
GameNews 테이블의 기존 광고성 데이터를 SpamNews로 이동시키는 스크립트
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = "backend/storage/db/portfolio.db"
AD_KEYWORDS = ["이벤트", "세미나", "기획전", "가이드북", "서포터즈", "참가자 모집", "수강생 모집"]

def move_ads():
    if not os.path.exists(DB_PATH):
        print(f"Error: DB file not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 1. 대상 찾기
        query_parts = ["title LIKE ?"] * len(AD_KEYWORDS)
        where_clause = " OR ".join(query_parts)
        params = [f"%{kw}%" for kw in AD_KEYWORDS]

        cursor.execute(f"SELECT * FROM game_news WHERE source_type = 'news' AND ({where_clause})", params)
        rows = cursor.fetchall()
        
        if not rows:
            print("No ads found in GameNews.")
            return

        print(f"Found {len(rows)} potential ads. Moving to spam_news...")

        moved_count = 0
        for row in rows:
            # 어떤 키워드 때문에 잡혔는지 확인
            reason = next((kw for kw in AD_KEYWORDS if kw in row["title"]), "Unknown")
            
            # spam_news에 삽입
            cursor.execute("""
                INSERT INTO spam_news (
                    content_hash, game_tag, category_tag, is_international,
                    event_time, source_type, source_name, title, url,
                    full_content, summary, published_at, spam_reason,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["content_hash"], row["game_tag"], row["category_tag"], row["is_international"],
                row["event_time"], row["source_type"], row["source_name"], row["title"], row["url"],
                row["full_content"], row["summary"], row["published_at"], f"Migration: {reason}",
                row["created_at"], datetime.now().isoformat()
            ))
            
            # game_news에서 삭제
            cursor.execute("DELETE FROM game_news WHERE id = ?", (row["id"],))
            moved_count += 1

        conn.commit()
        print(f"Successfully moved {moved_count} articles to spam_news.")
        
    except Exception as e:
        print(f"Failed to move ads: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    move_ads()
