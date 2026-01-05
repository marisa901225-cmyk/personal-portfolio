#!/usr/bin/env python3
"""
Match securities firm cashflows with bank transactions to verify investment principal.

This script analyzes:
1. Securities firm deposits/withdrawals (from Excel Cashflows_For_XIRR)
2. Bank investment/transfer transactions (from expenses table)
3. Matches them by date and amount
"""

import pandas as pd
import sqlite3
from pathlib import Path
from datetime import timedelta

REPO_ROOT = Path(__file__).resolve().parents[2]
EXCEL_PATH = REPO_ROOT / "combined_statements_valuation.xlsx"
DB_PATH = REPO_ROOT / "backend" / "portfolio.db"


def load_securities_cashflows():
    """Load cashflows from securities firms (Excel)"""
    print("📊 Loading securities firm cashflows...")
    xls = pd.ExcelFile(EXCEL_PATH)
    df = pd.read_excel(xls, sheet_name='Cashflows_For_XIRR')
    
    # Convert date
    df['거래일자'] = pd.to_datetime(df['거래일자'], errors='coerce')
    
    # Filter 2025
    df_2025 = df[df['거래일자'].dt.year == 2025].copy()
    
    # Clean amount column
    df_2025['금액_clean'] = df_2025['금액'].apply(lambda x: abs(float(x)) if pd.notna(x) else 0)
    
    # Determine direction (negative = deposit into securities, positive = withdrawal from securities)
    # In XIRR convention: negative = money into investment
    df_2025['direction'] = df_2025['현금흐름'].apply(lambda x: 'DEPOSIT' if x < 0 else 'WITHDRAWAL')
    
    print(f"  ✅ Found {len(df_2025)} securities cashflows in 2025")
    print(f"     Deposits: {len(df_2025[df_2025['direction'] == 'DEPOSIT'])}")
    print(f"     Withdrawals: {len(df_2025[df_2025['direction'] == 'WITHDRAWAL'])}")
    
    return df_2025


def load_bank_transactions():
    """Load bank investment/transfer transactions (from expenses table)"""
    print("\n🏦 Loading bank transactions...")
    conn = sqlite3.connect(DB_PATH)
    
    # Get investment and transfer transactions
    # IMPORTANT: 투자 category convention:
    #   - Positive amount = money sent TO securities (bank withdrawal)
    #   - Negative amount = money FROM securities (bank deposit / income)
    # Other categories follow normal convention:
    #   - Positive = income, Negative = spending
    query = """
        SELECT date, merchant, category, amount, id
        FROM expenses 
        WHERE date >= '2025-01-01' 
        AND category IN ('이체', '투자')
        ORDER BY date, amount
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    df['date'] = pd.to_datetime(df['date'])
    df['amount_abs'] = df['amount'].abs()
    
    # Determine direction based on category and amount
    # 투자: positive = deposit TO securities, negative = withdrawal FROM securities
    # 이체: normal convention
    def determine_direction(row):
        if row['category'] == '투자':
            return 'DEPOSIT' if row['amount'] > 0 else 'WITHDRAWAL'
        else:
            # 이체: negative = spending/deposit, positive = income/withdrawal
            return 'DEPOSIT' if row['amount'] < 0 else 'WITHDRAWAL'
    
    df['direction'] = df.apply(determine_direction, axis=1)
    
    # Filter out small amounts (통신요금 etc.)
    df = df[df['amount_abs'] >= 10000].copy()
    
    print(f"  ✅ Found {len(df)} bank transactions (≥10,000 KRW)")
    print(f"     Deposits (to securities): {len(df[df['direction'] == 'DEPOSIT'])}")
    print(f"     Withdrawals (from securities): {len(df[df['direction'] == 'WITHDRAWAL'])}")
    
    return df


def match_transactions(df_securities, df_bank, tolerance_days=3, tolerance_amount=1000):
    """
    Match securities and bank transactions.
    
    Now that bank direction is properly determined:
    - Securities DEPOSIT = Bank DEPOSIT (both mean money going TO securities)
    - Securities WITHDRAWAL = Bank WITHDRAWAL (both mean money coming FROM securities)
    
    Args:
        tolerance_days: Allow date difference up to this many days
        tolerance_amount: Allow amount difference up to this much (KRW)
    """
    print(f"\n🔍 Matching transactions (±{tolerance_days} days, ±{tolerance_amount:,} KRW)...\n")
    
    matches = []
    unmatched_securities = []
    unmatched_bank = []
    
    used_bank_ids = set()
    
    # Try to match each securities transaction
    for idx, sec_row in df_securities.iterrows():
        sec_date = sec_row['거래일자']
        sec_amount = sec_row['금액_clean']
        sec_direction = sec_row['direction']
        
        # Look for matching bank transaction
        # SAME direction (both deposits or both withdrawals), within date range, similar amount
        candidates = df_bank[
            (df_bank['direction'] == sec_direction) &
            (df_bank['date'] >= sec_date - timedelta(days=tolerance_days)) &
            (df_bank['date'] <= sec_date + timedelta(days=tolerance_days)) &
            (df_bank['amount_abs'] >= sec_amount - tolerance_amount) &
            (df_bank['amount_abs'] <= sec_amount + tolerance_amount) &
            (~df_bank['id'].isin(used_bank_ids))
        ].copy()
        
        if len(candidates) > 0:
            # Take the closest match by date and amount
            candidates['date_diff'] = (candidates['date'] - sec_date).abs()
            candidates['amount_diff'] = (candidates['amount_abs'] - sec_amount).abs()
            candidates['score'] = candidates['date_diff'].dt.days + candidates['amount_diff'] / 100000
            
            best_match = candidates.sort_values('score').iloc[0]
            
            matches.append({
                'sec_date': sec_date,
                'bank_date': best_match['date'],
                'direction': sec_direction,
                'sec_amount': sec_amount,
                'bank_amount': best_match['amount_abs'],
                'amount_diff': abs(sec_amount - best_match['amount_abs']),
                'date_diff_days': (best_match['date'] - sec_date).days,
                'sec_account': sec_row['계좌번호'],
                'bank_merchant': best_match['merchant'],
                'bank_category': best_match['category'],
                'bank_id': best_match['id']
            })
            
            used_bank_ids.add(best_match['id'])
        else:
            unmatched_securities.append({
                'date': sec_date,
                'direction': sec_direction,
                'amount': sec_amount,
                'account': sec_row['계좌번호'],
                'type': sec_row['거래구분']
            })
    
    # Find unmatched bank transactions
    for idx, bank_row in df_bank.iterrows():
        if bank_row['id'] not in used_bank_ids:
            unmatched_bank.append({
                'date': bank_row['date'],
                'direction': bank_row['direction'],
                'amount': bank_row['amount_abs'],
                'merchant': bank_row['merchant'],
                'category': bank_row['category']
            })
    
    return pd.DataFrame(matches), pd.DataFrame(unmatched_securities), pd.DataFrame(unmatched_bank)


def print_results(df_matched, df_unmatched_sec, df_unmatched_bank):
    """Print matching results"""
    
    print("=" * 100)
    print(f"📊 MATCHING RESULTS")
    print("=" * 100)
    
    # Summary
    total_sec = len(df_matched) + len(df_unmatched_sec)
    total_bank = len(df_matched) + len(df_unmatched_bank)
    match_rate = len(df_matched) / total_sec * 100 if total_sec > 0 else 0
    
    print(f"\n✅ Matched: {len(df_matched)} pairs ({match_rate:.1f}% of securities transactions)")
    print(f"⚠️  Unmatched securities: {len(df_unmatched_sec)}")
    print(f"⚠️  Unmatched bank: {len(df_unmatched_bank)}")
    
    # Matched transactions
    if len(df_matched) > 0:
        print("\n" + "=" * 100)
        print("✅ MATCHED TRANSACTIONS")
        print("=" * 100)
        
        for direction in ['DEPOSIT', 'WITHDRAWAL']:
            df_dir = df_matched[df_matched['direction'] == direction]
            if len(df_dir) > 0:
                print(f"\n{'💰 DEPOSITS (to securities)' if direction == 'DEPOSIT' else '💸 WITHDRAWALS (from securities)'}")
                print("-" * 100)
                
                for _, row in df_dir.iterrows():
                    date_info = f"{row['sec_date'].strftime('%Y-%m-%d')}"
                    if row['date_diff_days'] != 0:
                        date_info += f" (은행: {row['bank_date'].strftime('%m-%d')}, {row['date_diff_days']:+d}일)"
                    
                    amount_info = f"{row['sec_amount']:>12,.0f}원"
                    if row['amount_diff'] > 0:
                        amount_info += f" (차이: {row['amount_diff']:,.0f}원)"
                    
                    print(f"  {date_info:<30} {amount_info:<30} {row['bank_merchant']}")
        
        # Calculate totals
        total_deposits = df_matched[df_matched['direction'] == 'DEPOSIT']['sec_amount'].sum()
        total_withdrawals = df_matched[df_matched['direction'] == 'WITHDRAWAL']['sec_amount'].sum()
        net_investment = total_deposits - total_withdrawals
        
        print("\n" + "=" * 100)
        print(f"💰 TOTAL DEPOSITS:     {total_deposits:>15,.0f} KRW")
        print(f"💸 TOTAL WITHDRAWALS:  {total_withdrawals:>15,.0f} KRW")
        print(f"📊 NET INVESTMENT:     {net_investment:>15,.0f} KRW")
        print("=" * 100)
    
    # Unmatched securities transactions
    if len(df_unmatched_sec) > 0:
        print("\n" + "=" * 100)
        print("⚠️  UNMATCHED SECURITIES TRANSACTIONS")
        print("=" * 100)
        
        for direction in ['DEPOSIT', 'WITHDRAWAL']:
            df_dir = df_unmatched_sec[df_unmatched_sec['direction'] == direction]
            if len(df_dir) > 0:
                print(f"\n{direction}S:")
                for _, row in df_dir.iterrows():
                    print(f"  {row['date'].strftime('%Y-%m-%d')}  {row['amount']:>12,.0f}원  {row['type']:<20}  {row['account']}")
    
    # Unmatched bank transactions
    if len(df_unmatched_bank) > 0:
        print("\n" + "=" * 100)
        print("⚠️  UNMATCHED BANK TRANSACTIONS")
        print("=" * 100)
        
        for direction in ['DEPOSIT', 'WITHDRAWAL']:
            df_dir = df_unmatched_bank[df_unmatched_bank['direction'] == direction]
            if len(df_dir) > 0:
                print(f"\n{direction}S:")
                for _, row in df_dir.iterrows():
                    print(f"  {row['date'].strftime('%Y-%m-%d')}  {row['amount']:>12,.0f}원  {row['category']:<10}  {row['merchant']}")


def main():
    print("🚀 Starting cashflow matching analysis\n")
    
    # Load data
    df_securities = load_securities_cashflows()
    df_bank = load_bank_transactions()
    
    # Match transactions
    df_matched, df_unmatched_sec, df_unmatched_bank = match_transactions(
        df_securities, 
        df_bank,
        tolerance_days=3,
        tolerance_amount=1000
    )
    
    # Print results
    print_results(df_matched, df_unmatched_sec, df_unmatched_bank)
    
    # Save results
    output_file = REPO_ROOT / "cashflow_matching_report.csv"
    df_matched.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 Detailed results saved to: {output_file}")


if __name__ == "__main__":
    main()
