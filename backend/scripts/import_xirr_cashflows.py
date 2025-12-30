import pandas as pd
import sqlite3
from datetime import datetime
import os

EXCEL_PATH = "combined_statements_valuation.xlsx"
DB_PATH = "backend/portfolio.db"

def import_cashflows():
    if not os.path.exists(EXCEL_PATH):
        # Try parent if run from backend/scripts
        EXCEL_PATH_ALT = "../../combined_statements_valuation.xlsx"
        if os.path.exists(EXCEL_PATH_ALT):
            print(f"Using relative path: {EXCEL_PATH_ALT}")
            import_cashflows_with_paths(EXCEL_PATH_ALT, "../portfolio.db")
            return
        print(f"Error: {EXCEL_PATH} not found.")
        return
    
    import_cashflows_with_paths(EXCEL_PATH, DB_PATH)

def import_cashflows_with_paths(excel_p, db_p):
    print(f"Reading Excel: {excel_p}")
    df = pd.read_excel(excel_p, sheet_name='Cashflows_For_XIRR')
    df = df[df['기관'] != '(평가금액)']
    df['거래일자'] = pd.to_datetime(df['거래일자'])
    
    conn = sqlite3.connect(db_p)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM external_cashflows")
    
    count = 0
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    user_id = 1
    
    for _, row in df.iterrows():
        if pd.isna(row['거래일자']) or pd.isna(row['현금흐름']):
            continue
        date_str = row['거래일자'].strftime('%Y-%m-%d')
        amount = float(row['현금흐름'])
        description = f"[{row['방향']}] {row['거래구분']} ({row['기관']})"
        account_info = str(row['계좌번호']) if not pd.isna(row['계좌번호']) else None
        cursor.execute("""
            INSERT INTO external_cashflows 
            (user_id, date, amount, description, account_info, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, date_str, amount, description, account_info, now, now))
        count += 1
    
    conn.commit()
    conn.close()
    print(f"Imported {count} external cashflow records into {db_p}.")

if __name__ == "__main__":
    import_cashflows()
