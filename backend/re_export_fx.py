import sqlite3
import pandas as pd
import os

db_path = "/home/dlckdgn/personal-portfolio/backend/storage/db/portfolio.db"
output_path = "/home/dlckdgn/personal-portfolio/backend/storage/db/fx_transactions_export.csv"

def re_export_fx():
    try:
        conn = sqlite3.connect(db_path)
        # 전체 데이터 추출 (ID 순으로 정렬)
        query = "SELECT * FROM fx_transactions ORDER BY id ASC"
        df = pd.read_sql_query(query, conn)
        
        # utf-8-sig로 저장해서 엑셀 호환성 확보
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"Successfully re-exported fx_transactions to {output_path}")
        print(f"Total rows exported: {len(df)}")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    re_export_fx()
