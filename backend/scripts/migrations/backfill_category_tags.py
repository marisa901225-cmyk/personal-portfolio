import sqlite3
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BACKEND_DIR, "storage", "db", "portfolio.db")

def backfill():
    print(f"🔍 Backfilling categories at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print(f"❌ Error: Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 태그가 없는 뉴스 데이터 조회
    cursor.execute("SELECT id, title, game_tag, source_name, full_content FROM game_news WHERE category_tag IS NULL AND source_type = 'news'")
    rows = cursor.fetchall()
    
    count = 0
    for row_id, title, game_tag, source_name, content in rows:
        full_text = f"{title} {content}".lower()
        category_tag = "General"
        is_international = 0
        
        # Google News인 경우
        if "Google" in source_name:
            if any(kw in full_text for kw in ["fed", "fomc", "interest rate", "inflation", "cpi", "ecb"]):
                category_tag = "Macro"
                is_international = 1
            elif any(kw in full_text for kw in ["nvidia", "semiconductor", "chip", "amd", "hbm"]):
                category_tag = "Tech/Semicon"
            elif any(kw in full_text for kw in ["tesla", "ev", "electric vehicle"]):
                category_tag = "EV/Auto"
            elif any(kw in full_text for kw in ["s&p", "nasdaq", "dow", "stock", "market"]):
                category_tag = "Market"
            elif any(kw in full_text for kw in ["crypto", "bitcoin", "ethereum"]):
                category_tag = "Crypto"
        
        # Naver News 또는 기타
        else:
            if any(kw in full_text for kw in ["lck", "lol", "롤", "티원", "젠지", "월즈"]):
                category_tag = "LCK"
            elif any(kw in full_text for kw in ["vct", "발로", "퍼시픽"]):
                category_tag = "VCT"
            elif any(kw in full_text for kw in ["삼성", "반도체", "hbm", "하이닉스"]):
                category_tag = "Tech/Semicon"
            elif any(kw in full_text for kw in ["환율", "달러", "금리", "한국은행"]):
                category_tag = "FX/Rates"
            elif any(kw in full_text for kw in ["fomc", "연준", "cpi", "인플레이션"]):
                category_tag = "Macro"
            elif any(kw in full_text for kw in ["코스피", "코스닥", "주식시장"]):
                category_tag = "Market"
            elif any(kw in full_text for kw in ["비트코인", "코인", "가상자산"]):
                category_tag = "Crypto"

        cursor.execute("UPDATE game_news SET category_tag = ?, is_international = ? WHERE id = ?", (category_tag, is_international, row_id))
        count += 1
    
    conn.commit()
    conn.close()
    print(f"✅ Successfully backfilled {count} news records.")

if __name__ == "__main__":
    backfill()
