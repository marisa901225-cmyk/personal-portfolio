import sqlite3
import pandas as pd
import os

db_path = "/home/dlckdgn/personal-portfolio/backend/storage/db/portfolio.db"
output_dir = "/home/dlckdgn/personal-portfolio/backend/storage/db/"

def export_table(table_name, filename, custom_query=None):
    try:
        conn = sqlite3.connect(db_path)
        query = custom_query if custom_query else f"SELECT * FROM {table_name}"
        df = pd.read_sql_query(query, conn)
        output_path = os.path.join(output_dir, filename)
        # utf-8-sig로 저장해서 엑셀에서도 한글이 안 깨지게 함
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"Successfully exported {table_name} to {filename}")
        conn.close()
    except Exception as e:
        print(f"Error exporting {table_name}: {e}")

if __name__ == "__main__":
    # 거래내역 추출 (assets 테이블과 JOIN하여 종목명과 티커 포함)
    trades_query = """
    SELECT 
        t.id, t.timestamp, a.name as asset_name, a.ticker, 
        t.type, t.quantity, t.price, t.realized_delta, t.note,
        t.user_id, t.asset_id
    FROM trades t
    LEFT JOIN assets a ON t.asset_id = a.id
    ORDER BY t.timestamp DESC
    """
    export_table("trades", "trades_export.csv", custom_query=trades_query)
    
    # 입출금내역 추출
    export_table("external_cashflows", "external_cashflows_export.csv")
    print("All exports completed with utf-8-sig encoding and asset names!")
