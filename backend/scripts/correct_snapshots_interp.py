import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db")
REAL_ESTATE_VALUE = 150_000_000

# Main Account Stock Values (End of Month)
MAIN_ANCHORS = {
    "2025-01": 81_400_069,
    "2025-02": 79_153_208,
    "2025-03": 73_881_672,
    "2025-04": 72_455_967,
    "2025-05": 76_118_167,
    "2025-06": 79_445_811,
    "2025-07": 85_919_010,
    "2025-08": 89_622_396,
    "2025-09": 94_531_504,
    "2025-10": 103_121_234,
    "2025-11": 104_458_378,
    "2025-12": 106_460_009,
}

# Pension Account Stock Values (End of Month)
PENSION_ANCHORS = {
    "2025-01": 18_593_036,
    "2025-02": 17_977_536,
    "2025-03": 16_964_670,
    "2025-04": 16_495_260,
    "2025-05": 17_289_185,
    "2025-06": 17_881_916,
    "2025-07": 19_042_256,
    "2025-08": 19_276_757,
    "2025-09": 20_074_641,
    "2025-10": 21_192_808,
    "2025-11": 21_608_489,
    "2025-12": 21_375_726,
}

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # 1. Load all snapshots timestamps
    # Values are corrupted, so we only need timestamps to fill
    query = """
    SELECT id, snapshot_at
    FROM portfolio_snapshots 
    WHERE date(snapshot_at) >= '2025-01-01'
    ORDER BY snapshot_at
    """
    df = pd.read_sql_query(query, conn)
    df['snapshot_at'] = pd.to_datetime(df['snapshot_at'])
    df['date_str'] = df['snapshot_at'].dt.strftime('%Y-%m-%d')
    df['month_str'] = df['snapshot_at'].dt.strftime('%Y-%m')
    
    # 2. Assign Target Values to Anchor Dates
    df['stock_target'] = np.nan
    
    print("=== Interpolation Targets (Stock Only) ===")
    
    # Pre-fill anchors
    for month in MAIN_ANCHORS.keys():
        target_main = MAIN_ANCHORS.get(month, 0)
        target_pension = PENSION_ANCHORS.get(month, 0)
        target_total_stock = target_main + target_pension
        
        # Find the last snapshot in this month
        mask = df['month_str'] == month
        if not mask.any():
            print(f"Warning: No data for {month}")
            continue
            
        # Get last index in this month
        last_idx = df[mask].index[-1]
        
        # Set target value explicitly
        df.loc[last_idx, 'stock_target'] = target_total_stock
        print(f"{month}: Set Target {target_total_stock:,.0f} at {df.loc[last_idx, 'date_str']}")

    # 3. Interpolate Values
    df = df.set_index('snapshot_at')
    
    # Time-based interpolation of the Value directly (Smooth straight lines)
    df['stock_target'] = df['stock_target'].interpolate(method='time')
    
    # Fill edges
    df['stock_target'] = df['stock_target'].bfill().ffill()
    
    # 4. Calculate Final DB Value
    # DB must include RE because Frontend subtracts RE
    # new_total = stock_target + 150M
    df['new_total'] = df['stock_target'] + REAL_ESTATE_VALUE
    
    # 5. Update DB
    print("\n=== Updating Database with DIRECT INTERPOLATION ===")
    cursor = conn.cursor()
    
    updates = []
    for idx, row in df.iterrows():
        updates.append((row['new_total'], row['id']))
        
    cursor.executemany(
        "UPDATE portfolio_snapshots SET total_value = ? WHERE id = ?",
        updates
    )
    conn.commit()
    print(f"Updated {len(updates)} rows.")
    
    conn.close()

if __name__ == "__main__":
    main()
