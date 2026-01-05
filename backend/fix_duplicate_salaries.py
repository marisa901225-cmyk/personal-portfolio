#!/usr/bin/env python3
"""
Fix duplicate salary entries in the expenses table.

This script removes duplicate salary entries that have amount = 0,
keeping only the entries with non-zero amounts.
"""

import sqlite3
from pathlib import Path


def main():
    # Database path
    db_path = Path(__file__).parent / "portfolio.db"
    
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return
    
    print(f"🔍 Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # First, let's see what we're dealing with
    print("\n📊 Current salary entries status:")
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN amount = 0 THEN 1 END) as zero_amount,
            COUNT(CASE WHEN amount != 0 THEN 1 END) as non_zero
        FROM expenses 
        WHERE category = '급여'
    """)
    total, zero, non_zero = cursor.fetchone()
    print(f"   Total entries: {total}")
    print(f"   Zero amount: {zero}")
    print(f"   Non-zero amount: {non_zero}")
    
    if zero == 0:
        print("\n✅ No zero-amount salary entries found. Nothing to clean up!")
        conn.close()
        return
    
    # Show duplicates that will be deleted
    print(f"\n🗑️  Found {zero} zero-amount salary entries to delete:")
    cursor.execute("""
        SELECT id, date, amount, merchant, method
        FROM expenses
        WHERE category = '급여' AND amount = 0
        ORDER BY date DESC
    """)
    
    duplicates = cursor.fetchall()
    for dup in duplicates:
        print(f"   ID {dup[0]}: {dup[1]} | Amount: ₩{dup[2]:,.0f} | {dup[3]} | {dup[4]}")
    
    # Ask for confirmation
    print(f"\n⚠️  About to delete {zero} zero-amount salary entries.")
    confirm = input("Continue? (yes/no): ").strip().lower()
    
    if confirm != 'yes':
        print("❌ Operation cancelled.")
        conn.close()
        return
    
    # Delete zero-amount salary entries
    print("\n🧹 Deleting zero-amount salary entries...")
    cursor.execute("""
        DELETE FROM expenses
        WHERE category = '급여' AND amount = 0
    """)
    
    deleted_count = cursor.rowcount
    conn.commit()
    
    print(f"✅ Deleted {deleted_count} entries")
    
    # Verify results
    print("\n📊 After cleanup:")
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN amount = 0 THEN 1 END) as zero_amount,
            COUNT(CASE WHEN amount != 0 THEN 1 END) as non_zero
        FROM expenses 
        WHERE category = '급여'
    """)
    total, zero, non_zero = cursor.fetchone()
    print(f"   Total entries: {total}")
    print(f"   Zero amount: {zero}")
    print(f"   Non-zero amount: {non_zero}")
    
    # Show remaining salary entries
    print("\n💰 Remaining salary entries:")
    cursor.execute("""
        SELECT date, amount, merchant
        FROM expenses
        WHERE category = '급여'
        ORDER BY date DESC
        LIMIT 10
    """)
    
    for row in cursor.fetchall():
        print(f"   {row[0]} | ₩{row[1]:,.0f} | {row[2]}")
    
    conn.close()
    print("\n✅ Cleanup completed successfully!")


if __name__ == "__main__":
    main()
