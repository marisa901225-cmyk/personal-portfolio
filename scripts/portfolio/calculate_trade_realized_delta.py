#!/usr/bin/env python3
"""
Calculate and update realized_delta for all SELL trades.

This script goes through all trades chronologically and calculates
the realized profit/loss for each SELL transaction based on the
average cost at that time.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "backend" / "storage" / "db" / "portfolio.db"


def calculate_realized_deltas():
    """Calculate realized_delta for all SELL trades"""
    
    print("🔄 Calculating realized_delta for all SELL trades...\n")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Get all assets
        cursor.execute("SELECT DISTINCT asset_id FROM trades ORDER BY asset_id")
        asset_ids = [row[0] for row in cursor.fetchall()]
        
        updated_count = 0
        total_realized = 0
        
        for asset_id in asset_ids:
            # Get asset name
            cursor.execute("SELECT name, ticker FROM assets WHERE id = ?", (asset_id,))
            asset_row = cursor.fetchone()
            if not asset_row:
                continue
            
            asset_name, ticker = asset_row
            
            # Get all trades for this asset in chronological order
            cursor.execute("""
                SELECT id, type, quantity, price, timestamp, realized_delta
                FROM trades
                WHERE asset_id = ?
                ORDER BY timestamp ASC, id ASC
            """, (asset_id,))
            
            trades = cursor.fetchall()
            
            if not trades:
                continue
            
            # Track state
            current_amount = 0.0
            current_avg_cost = 0.0
            asset_realized = 0.0
            
            for trade_id, trade_type, quantity, price, timestamp, old_realized_delta in trades:
                if trade_type == 'BUY':
                    prev_amount = current_amount
                    prev_avg_cost = current_avg_cost if current_avg_cost > 0 else price
                    
                    new_amount = prev_amount + quantity
                    if new_amount > 0:
                        new_avg_cost = (prev_amount * prev_avg_cost + quantity * price) / new_amount
                    else:
                        new_avg_cost = price
                    
                    current_amount = new_amount
                    current_avg_cost = new_avg_cost
                
                elif trade_type == 'SELL':
                    avg_cost = current_avg_cost if current_avg_cost > 0 else price
                    realized_delta = (price - avg_cost) * quantity
                    
                    # Update trade with realized_delta
                    if old_realized_delta != realized_delta:
                        cursor.execute("""
                            UPDATE trades
                            SET realized_delta = ?
                            WHERE id = ?
                        """, (realized_delta, trade_id))
                        
                        if abs(realized_delta) > 100:  # Only print significant ones
                            print(f"  ✅ {asset_name}: {timestamp[:10]} SELL {quantity}개 @ ₩{price:,.0f} = {realized_delta:+,.0f} KRW")
                        
                        updated_count += 1
                        asset_realized += realized_delta
                    
                    current_amount -= quantity
            
            if abs(asset_realized) > 100:
                total_realized += asset_realized
        
        conn.commit()
        
        print(f"\n✅ Updated {updated_count} SELL trades with realized_delta")
        print(f"📊 Total calculated realized profit: {total_realized:,.0f} KRW")
        
        # Verify by checking trades table
        cursor.execute("""
            SELECT COUNT(*), SUM(realized_delta)
            FROM trades
            WHERE type = 'SELL' AND realized_delta IS NOT NULL
        """)
        
        row = cursor.fetchone()
        print(f"\n📋 Verification:")
        print(f"   SELL trades with realized_delta: {row[0]}")
        print(f"   Sum of all realized_delta: {row[1]:,.0f} KRW")
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return 1
    finally:
        conn.close()
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(calculate_realized_deltas())
