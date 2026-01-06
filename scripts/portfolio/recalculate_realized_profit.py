#!/usr/bin/env python3
"""
Recalculate realized_profit for all assets based on their trade history.

This script rebuilds the asset state (amount, purchase_price, realized_profit)
by replaying all trades in chronological order.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "backend" / "storage" / "db" / "portfolio.db"


def recalculate_realized_profits():
    """Recalculate realized profits for all assets"""
    
    print("🔄 Recalculating realized profits from trade history...\n")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Get all assets (including deleted ones to preserve history)
        cursor.execute("""
            SELECT id, user_id, name, ticker 
            FROM assets 
            ORDER BY id
        """)
        assets = cursor.fetchall()
        
        updated_count = 0
        
        for asset_id, user_id, name, ticker in assets:
            # Get all trades for this asset in chronological order
            cursor.execute("""
                SELECT type, quantity, price, timestamp
                FROM trades
                WHERE asset_id = ?
                ORDER BY timestamp ASC, id ASC
            """, (asset_id,))
            
            trades = cursor.fetchall()
            
            if not trades:
                continue
            
            # Replay trades to calculate state
            current_amount = 0.0
            current_purchase_price = 0.0
            realized_profit = 0.0
            
            for trade_type, quantity, price, timestamp in trades:
                if trade_type == 'BUY':
                    prev_amount = current_amount
                    prev_purchase_price = current_purchase_price if current_purchase_price > 0 else price
                    
                    new_amount = prev_amount + quantity
                    if new_amount > 0:
                        new_purchase_price = (
                            (prev_amount * prev_purchase_price + quantity * price) / new_amount
                        )
                    else:
                        new_purchase_price = price
                    
                    current_amount = new_amount
                    current_purchase_price = new_purchase_price
                
                elif trade_type == 'SELL':
                    avg_cost = current_purchase_price if current_purchase_price > 0 else price
                    realized_delta = (price - avg_cost) * quantity
                    realized_profit += realized_delta
                    current_amount -= quantity
            
            # Update asset
            cursor.execute("""
                UPDATE assets
                SET 
                    amount = ?,
                    purchase_price = ?,
                    realized_profit = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                current_amount,
                current_purchase_price if current_purchase_price > 0 else None,
                realized_profit,
                datetime.now(),
                asset_id
            ))
            
            if realized_profit != 0:
                print(f"  ✅ {name} ({ticker}): {realized_profit:>15,.0f} KRW realized")
                updated_count += 1
        
        conn.commit()
        print(f"\n✅ Updated {updated_count} assets with realized profits")
        
        # Show summary
        cursor.execute("""
            SELECT 
                COUNT(*) as count,
                SUM(realized_profit) as total_realized
            FROM assets
            WHERE deleted_at IS NULL AND realized_profit != 0
        """)
        
        row = cursor.fetchone()
        if row:
            print(f"\n📊 Summary:")
            print(f"   Assets with realized profit: {row[0]}")
            print(f"   Total realized profit: {row[1]:,.0f} KRW")
    
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
    sys.exit(recalculate_realized_profits())
