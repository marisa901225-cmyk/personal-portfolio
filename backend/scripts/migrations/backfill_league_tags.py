import sqlite3
import os

# backend 디렉토리 경로
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")

def backfill():
    print(f"🔍 Backfilling database at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. e스포츠 일정 데이터에 대해 태깅
    cursor.execute("SELECT id, title, full_content FROM game_news WHERE source_type = 'schedule'")
    rows = cursor.fetchall()
    
    count = 0
    for row_id, title, content in rows:
        full_text = f"{title} {content}".lower()
        league_tag = "기타"
        is_international = 0
        
        if "lck" in full_text:
            if "challengers" in full_text or "cl" in full_text:
                league_tag = "LCK-CL"
            else:
                league_tag = "LCK"
        elif "lpl" in full_text:
            league_tag = "LPL"
        elif "lec" in full_text:
            league_tag = "LEC"
        elif "lcs" in full_text:
            league_tag = "LCS"
        elif any(kw in full_text for kw in ["worlds", "msi", "mid-season invitational"]):
            league_tag = "Worlds/MSI"
            is_international = 1
        elif any(kw in full_text for kw in ["champions", "masters", "vct"]):
            league_tag = "VCT"
            is_international = 1
            
        cursor.execute("UPDATE game_news SET league_tag = ?, is_international = ? WHERE id = ?", (league_tag, is_international, row_id))
        count += 1
    
    conn.commit()
    conn.close()
    print(f"✅ Successfully backfilled {count} records.")

if __name__ == "__main__":
    backfill()
