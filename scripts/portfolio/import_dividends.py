#!/usr/bin/env python3
"""
Import dividends from combined_statements_valuation.xlsx into external_cashflows table.
"""

import pandas as pd
import sqlite3
from datetime import datetime
from pathlib import Path
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "backend" / "storage" / "db" / "portfolio.db"
EXCEL_PATH = REPO_ROOT / "combined_statements_valuation.xlsx"


def import_dividends():
    print("📊 Importing dividends from Excel to external_cashflows...\n")
    
    if not EXCEL_PATH.exists():
        print(f"❌ Excel file not found: {EXCEL_PATH}")
        return 1
        
    df = pd.read_excel(EXCEL_PATH, sheet_name='All_Normalized')
    
    # Filter for dividends/interest/ETF distributions
    div_keywords = ['배당', '분배금', '이자']
    df_div = df[df['거래구분'].str.contains('|'.join(div_keywords), na=False)].copy()
    
    if len(df_div) == 0:
        print("ℹ️ No dividend transactions found in Excel.")
        return 0
        
    print(f"🔍 Found {len(df_div)} dividend-like transactions in Excel.")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get user_id (assume first user)
    cursor.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    user_row = cursor.fetchone()
    if not user_row:
        print("❌ No user found in DB.")
        return 1
    user_id = user_row[0]
    
    # Use a default FX rate for USD dividends if not specified in the row
    DEFAULT_FX = 1400.0
    
    imported_count = 0
    skipped_count = 0
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for _, row in df_div.iterrows():
        date_str = pd.to_datetime(row['거래일자']).strftime("%Y-%m-%d")
        
        # Determine amount (Negative for deposit in XIRR convention used in external_cashflows)
        amount = 0
        if not np.isnan(row['거래금액']) and row['거래금액'] > 0:
            amount = -float(row['거래금액'])
        elif row['통화코드'] == 'USD' and not np.isnan(row['외화정산금액']):
            rate = row['환율'] if not np.isnan(row['환율']) else DEFAULT_FX
            amount = -float(row['외화정산금액'] * rate)
        elif not np.isnan(row['입금액']) and row['입금액'] > 0:
            amount = -float(row['입금액'])
            
        if amount == 0:
            continue
            
        description = f"[{row['거래구분']}] {row['종목명']}"
        account_info = f"{row['기관']} ({row.get('원천파일', 'Excel')})"
        
        # Check for duplicates (same date, amount, description)
        cursor.execute("""
            SELECT id FROM external_cashflows 
            WHERE user_id = ? AND date = ? AND ABS(amount - ?) < 1.0 AND description = ?
        """, (user_id, date_str, amount, description))
        
        if cursor.fetchone():
            skipped_count += 1
            continue
            
        # Insert
        cursor.execute("""
            INSERT INTO external_cashflows (
                user_id, date, amount, description, account_info, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, date_str, amount, description, account_info, now, now))
        
        imported_count += 1
        
    conn.commit()
    conn.close()
    
    print(f"\n✅ Import completed:")
    print(f"   - Total found in Excel: {len(df_div)}")
    print(f"   - Newly imported: {imported_count}")
    print(f"   - Skipped (duplicates): {skipped_count}")
    
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(import_dividends())
