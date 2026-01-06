#!/usr/bin/env python3
"""
Restore assets table from backup database.

This script restores the assets table from the backup while preserving
the current trades, cashflows, and other tables.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DB = REPO_ROOT / "data_backup_reference" / "portfolio_2025-12-31.db"
CURRENT_DB = REPO_ROOT / "backend" / "storage" / "db" / "portfolio.db"


def restore_assets_from_backup():
    """Restore assets table from backup"""
    
    print("🔄 Restoring assets from backup...\n")
    
    if not BACKUP_DB.exists():
        print(f"❌ Backup not found: {BACKUP_DB}")
        return 1
    
    # Connect to databases
    backup_conn = sqlite3.connect(BACKUP_DB)
    current_conn = sqlite3.connect(CURRENT_DB)
    
    backup_cursor = backup_conn.cursor()
    current_cursor = current_conn.cursor()
    
    try:
        # Get all assets from backup
        backup_cursor.execute("""
            SELECT 
                id, user_id, name, ticker, category, currency,
                amount, current_price, purchase_price, realized_profit,
                index_group, cma_config, created_at, updated_at, deleted_at
            FROM assets
            ORDER BY id
        """)
        
        backup_assets = backup_cursor.fetchall()
        
        print(f"📦 Found {len(backup_assets)} assets in backup")
        
        # Clear current assets (soft delete all, then delete for real)
        print("\n🗑️  Clearing current assets...")
        current_cursor.execute("DELETE FROM assets")
        
        # Restore from backup
        print("📥 Restoring assets from backup...")
        
        restored_count = 0
        
        for asset in backup_assets:
            current_cursor.execute("""
                INSERT INTO assets (
                    id, user_id, name, ticker, category, currency,
                    amount, current_price, purchase_price, realized_profit,
                    index_group, cma_config, created_at, updated_at, deleted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, asset)
            
            if asset[14] is None:  # deleted_at is NULL (active asset)
                print(f"  ✅ {asset[2]}: {asset[6]:.2f} units, realized: {asset[9]:,.0f} KRW")
                restored_count += 1
        
        current_conn.commit()
        
        print(f"\n✅ Successfully restored {restored_count} active assets")
        
        # Verify
        current_cursor.execute("""
            SELECT 
                COUNT(*) as count,
                SUM(amount * current_price) as total_value,
                SUM(realized_profit) as total_realized
            FROM assets
            WHERE deleted_at IS NULL
        """)
        
        row = current_cursor.fetchone()
        print(f"\n📊 Restored portfolio summary:")
        print(f"   Active assets: {row[0]}")
        print(f"   Total value: {row[1]:,.0f} KRW")
        print(f"   Total realized profit: {row[2]:,.0f} KRW")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        current_conn.rollback()
        return 1
    finally:
        backup_conn.close()
        current_conn.close()
    
    return 0


if __name__ == "__main__":
    import sys
    
    response = input("⚠️  This will REPLACE all assets with backup data. Continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("Cancelled.")
        sys.exit(0)
    
    sys.exit(restore_assets_from_backup())
