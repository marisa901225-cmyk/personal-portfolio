#!/usr/bin/env python3
"""
Import matched cashflows into the database.

Takes the matched bank-securities transactions and imports them into
the external_cashflows table for accurate investment principal tracking.
"""

import pandas as pd
import sqlite3
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "backend" / "portfolio.db"
CSV_PATH = REPO_ROOT / "cashflow_matching_report_bank_files.csv"


def get_user_id():
    """Get the first user ID"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def check_existing_cashflow(conn, user_id, date, amount):
    """Check if a cashflow already exists for this date and amount"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM external_cashflows
        WHERE user_id = ? AND date = ? AND ABS(ABS(amount) - ?) < 100
    """, (user_id, date, abs(amount)))
    count = cursor.fetchone()[0]
    return count > 0


def import_matched_cashflows(dry_run=False):
    """Import matched cashflows into database"""
    
    if not CSV_PATH.exists():
        print(f"❌ CSV file not found: {CSV_PATH}")
        print("   Run scripts/cashflows/match_cashflows_bank_files.py first!")
        return 1
    
    print("🚀 Importing matched cashflows to database\n")
    
    # Load CSV
    df = pd.read_csv(CSV_PATH)
    print(f"📊 Loaded {len(df)} matched transactions from CSV")
    
    # Get user ID
    user_id = get_user_id()
    if not user_id:
        print("❌ No user found in database")
        return 1
    
    print(f"   User ID: {user_id}\n")
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    imported = 0
    skipped_exists = 0
    skipped_other = 0
    
    try:
        for idx, row in df.iterrows():
            # Parse data
            date = pd.to_datetime(row['sec_date']).date()
            direction = row['direction']
            amount = float(row['sec_amount'])
            
            # XIRR convention: negative = deposit (money into investment)
            # positive = withdrawal (money out of investment)
            if direction == 'DEPOSIT':
                amount_xirr = -abs(amount)
                desc_prefix = "증권계좌 입금"
            else:
                amount_xirr = abs(amount)
                desc_prefix = "증권계좌 출금"
            
            # Build description
            bank_date = pd.to_datetime(row['bank_date']).date()
            date_diff = int(row['date_diff_days'])
            amount_diff = float(row['amount_diff'])
            
            description = f"{desc_prefix} - {row['bank_name']} {row['bank_description'][:50]}"
            if date_diff != 0:
                description += f" (날짜차이: {date_diff:+d}일)"
            if amount_diff > 100:
                description += f" (금액차이: {amount_diff:,.0f}원)"
            
            # Check if already exists
            if check_existing_cashflow(conn, user_id, date, amount_xirr):
                if not dry_run:
                    print(f"  ⏭️  {date} {amount:>12,.0f}원 - 이미 존재함, 스킵")
                skipped_exists += 1
                continue
            
            # Insert
            if dry_run:
                print(f"  [DRY-RUN] {date} {amount:>12,.0f}원 ({direction}) - {description[:80]}")
            else:
                cursor.execute("""
                    INSERT INTO external_cashflows 
                    (user_id, date, amount, description, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    date,
                    amount_xirr,
                    description,
                    datetime.now(),
                    datetime.now()
                ))
                print(f"  ✅ {date} {amount:>12,.0f}원 ({direction})")
            
            imported += 1
        
        if not dry_run:
            conn.commit()
            print(f"\n✅ Successfully imported {imported} cashflows!")
        else:
            print(f"\n[DRY-RUN] Would import {imported} cashflows")
        
        if skipped_exists > 0:
            print(f"   ⏭️  Skipped {skipped_exists} existing entries")
        
        # Show summary
        if not dry_run:
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN amount < 0 THEN ABS(amount) ELSE 0 END) as total_deposits,
                    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) as total_withdrawals
                FROM external_cashflows
                WHERE user_id = ? AND date >= '2025-01-01'
            """, (user_id,))
            
            row = cursor.fetchone()
            print(f"\n📊 2025 Cashflows in DB:")
            print(f"   Total entries: {row[0]}")
            print(f"   Total deposits: {row[1]:,.0f} KRW")
            print(f"   Total withdrawals: {row[2]:,.0f} KRW")
            print(f"   Net investment: {row[1] - row[2]:,.0f} KRW")
    
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        return 1
    finally:
        conn.close()
    
    return 0


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Import matched cashflows to database")
    parser.add_argument('--dry-run', action='store_true', help='Show what would be imported without actually importing')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()
    
    if not args.force and not args.dry_run:
        print("⚠️  This will import cashflows into the database.")
        response = input("Continue? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("Cancelled.")
            return 0
    
    return import_matched_cashflows(dry_run=args.dry_run)


if __name__ == "__main__":
    import sys
    sys.exit(main())
