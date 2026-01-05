#!/usr/bin/env python3
"""
Match securities firm cashflows with actual bank transaction files.

Uses direct bank transaction Excel files to match with securities cashflows,
providing accurate investment principal tracking.
"""

import pandas as pd
from pathlib import Path
from datetime import timedelta
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
EXCEL_PATH = REPO_ROOT / "combined_statements_valuation.xlsx"
BANK_FILES = {
    "KB1": REPO_ROOT / "temp_unzipped" / "거래내역조회_20251231.xls",
    "KB2": REPO_ROOT / "temp_unzipped" / "거래내역조회_20251231(월급통장).xls",
    "WOORI": REPO_ROOT / "temp_unzipped" / "우리은행.xls",
}


def load_securities_cashflows():
    """Load cashflows from securities firms"""
    print("📊 Loading securities firm cashflows...")
    xls = pd.ExcelFile(EXCEL_PATH)
    df = pd.read_excel(xls, sheet_name='Cashflows_For_XIRR')
    
    df['거래일자'] = pd.to_datetime(df['거래일자'], errors='coerce')
    df_2025 = df[df['거래일자'].dt.year == 2025].copy()
    df_2025['금액_clean'] = df_2025['금액'].apply(lambda x: abs(float(x)) if pd.notna(x) else 0)
    df_2025['direction'] = df_2025['현금흐름'].apply(lambda x: 'DEPOSIT' if x < 0 else 'WITHDRAWAL')
    
    print(f"  ✅ Found {len(df_2025)} securities cashflows in 2025")
    print(f"     Deposits: {len(df_2025[df_2025['direction'] == 'DEPOSIT'])}")
    print(f"     Withdrawals: {len(df_2025[df_2025['direction'] == 'WITHDRAWAL'])}")
    
    return df_2025


def parse_kb_bank(file_path):
    """Parse KB bank transaction file"""
    df_raw = pd.read_excel(file_path)
    
    # Find header row (contains '거래일시')
    header_row = None
    for i in range(10):
        if '거래일시' in str(df_raw.iloc[i].values):
            header_row = i
            break
    
    if header_row is None:
        return pd.DataFrame()
    
    # Read with proper header
    df = pd.read_excel(file_path, skiprows=header_row)
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # Rename columns
    df = df.rename(columns={
        '거래일시': 'date',
        '적요': 'description',
        '출금액': 'withdrawal',
        '입금액': 'deposit'
    })
    
    # Parse date
    df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d %H:%M:%S', errors='coerce')
    
    # Clean amounts
    df['withdrawal'] = pd.to_numeric(df['withdrawal'], errors='coerce').fillna(0)
    df['deposit'] = pd.to_numeric(df['deposit'], errors='coerce').fillna(0)
    
    # Filter 2025
    df = df[df['date'].notna() & (df['date'].dt.year == 2025)].copy()
    
    return df[['date', 'description', 'withdrawal', 'deposit']]


def parse_woori_bank(file_path):
    """Parse Woori bank transaction file"""
    df_raw = pd.read_excel(file_path)
    
    # Find header row (contains '거래일시')
    header_row = None
    for i in range(10):
        if '거래일시' in str(df_raw.iloc[i].values):
            header_row = i
            break
    
    if header_row is None:
        return pd.DataFrame()
    
    # Read with proper header
    df = pd.read_excel(file_path, skiprows=header_row)
    df.columns = df.iloc[0]
    df = df[1:].reset_index(drop=True)
    
    # Rename columns
    df = df.rename(columns={
        '거래일시': 'date',
        '기재내용': 'description',
        '찾으신금액': 'withdrawal',
        '맡기신금액': 'deposit'
    })
    
    # Parse date
    df['date'] = pd.to_datetime(df['date'], format='%Y.%m.%d %H:%M', errors='coerce')
    
    # Clean amounts
    df['withdrawal'] = pd.to_numeric(df['withdrawal'], errors='coerce').fillna(0)
    df['deposit'] = pd.to_numeric(df['deposit'], errors='coerce').fillna(0)
    
    # Filter 2025
    df = df[df['date'].notna() & (df['date'].dt.year == 2025)].copy()
    
    return df[['date', 'description', 'withdrawal', 'deposit']]


def load_all_bank_transactions():
    """Load all bank transaction files"""
    print("\n🏦 Loading bank transactions...")
    
    all_transactions = []
    
    for bank_name, file_path in BANK_FILES.items():
        if not file_path.exists():
            print(f"  ⚠️  {bank_name}: File not found")
            continue
        
        try:
            if 'WOORI' in bank_name:
                df = parse_woori_bank(file_path)
            else:
                df = parse_kb_bank(file_path)
            
            df['bank'] = bank_name
            all_transactions.append(df)
            print(f"  ✅ {bank_name}: {len(df)} transactions")
        except Exception as e:
            print(f"  ❌ {bank_name}: Error - {e}")
    
    if not all_transactions:
        return pd.DataFrame()
    
    df_all = pd.concat(all_transactions, ignore_index=True)
    
    # Filter for large transactions (≥10,000 KRW) - these are likely investment-related
    df_large = df_all[(df_all['withdrawal'] >= 10000) | (df_all['deposit'] >= 10000)].copy()
    
    print(f"\n  📊 Total large transactions (≥10,000): {len(df_large)}")
    print(f"     Withdrawals: {len(df_large[df_large['withdrawal'] >= 10000])}")
    print(f"     Deposits: {len(df_large[df_large['deposit'] >= 10000])}")
    
    return df_large


def match_transactions(df_securities_cf, df_bank, tolerance_days=3, tolerance_amount=5000):
    """Match securities cashflows with bank transactions"""
    print(f"\n🔍 Matching transactions (±{tolerance_days} days, ±{tolerance_amount:,} KRW)...\n")
    
    matches = []
    unmatched_securities = []
    unmatched_bank = []
    
    used_bank_indices = set()
    
    for idx, sec_row in df_securities_cf.iterrows():
        sec_date = sec_row['거래일자']
        sec_amount = sec_row['금액_clean']
        sec_direction = sec_row['direction']
        
        # For DEPOSIT to securities: bank withdrawal > 0
        # For WITHDRAWAL from securities: bank deposit > 0
        if sec_direction == 'DEPOSIT':
            candidates = df_bank[
                (df_bank['withdrawal'] >= sec_amount - tolerance_amount) &
                (df_bank['withdrawal'] <= sec_amount + tolerance_amount) &
                (df_bank['date'] >= sec_date - timedelta(days=tolerance_days)) &
                (df_bank['date'] <= sec_date + timedelta(days=tolerance_days)) &
                (~df_bank.index.isin(used_bank_indices))
            ].copy()
            amount_col = 'withdrawal'
        else:
            candidates = df_bank[
                (df_bank['deposit'] >= sec_amount - tolerance_amount) &
                (df_bank['deposit'] <= sec_amount + tolerance_amount) &
                (df_bank['date'] >= sec_date - timedelta(days=tolerance_days)) &
                (df_bank['date'] <= sec_date + timedelta(days=tolerance_days)) &
                (~df_bank.index.isin(used_bank_indices))
            ].copy()
            amount_col = 'deposit'
        
        if len(candidates) > 0:
            candidates['date_diff'] = (candidates['date'] - sec_date).abs()
            candidates['amount_diff'] = (candidates[amount_col] - sec_amount).abs()
            candidates['score'] = candidates['date_diff'].dt.days + candidates['amount_diff'] / 100000
            
            best_match = candidates.sort_values('score').iloc[0]
            
            matches.append({
                'sec_date': sec_date,
                'bank_date': best_match['date'],
                'direction': sec_direction,
                'sec_amount': sec_amount,
                'bank_amount': best_match[amount_col],
                'amount_diff': abs(sec_amount - best_match[amount_col]),
                'date_diff_days': (best_match['date'] - sec_date).days,
                'sec_account': sec_row['계좌번호'],
                'bank_name': best_match['bank'],
                'bank_description': best_match['description']
            })
            
            used_bank_indices.add(best_match.name)
        else:
            unmatched_securities.append({
                'date': sec_date,
                'direction': sec_direction,
                'amount': sec_amount,
                'account': sec_row['계좌번호'],
                'type': sec_row['거래구분']
            })
    
    for idx, bank_row in df_bank.iterrows():
        if idx not in used_bank_indices:
            amount = bank_row['withdrawal'] if bank_row['withdrawal'] > 0 else bank_row['deposit']
            direction = 'DEPOSIT' if bank_row['withdrawal'] > 0 else 'WITHDRAWAL'
            
            unmatched_bank.append({
                'date': bank_row['date'],
                'direction': direction,
                'amount': amount,
                'bank': bank_row['bank'],
                'description': bank_row['description']
            })
    
    return pd.DataFrame(matches), pd.DataFrame(unmatched_securities), pd.DataFrame(unmatched_bank)


def print_results(df_matched, df_unmatched_sec, df_unmatched_bank):
    """Print matching results"""
    
    print("=" * 100)
    print(f"📊 MATCHING RESULTS")
    print("=" * 100)
    
    total_sec = len(df_matched) + len(df_unmatched_sec)
    total_bank = len(df_matched) + len(df_unmatched_bank)
    match_rate = len(df_matched) / total_sec * 100 if total_sec > 0 else 0
    
    print(f"\n✅ Matched: {len(df_matched)} pairs ({match_rate:.1f}% of securities transactions)")
    print(f"⚠️  Unmatched securities: {len(df_unmatched_sec)}")
    print(f"⚠️  Unmatched bank: {len(df_unmatched_bank)}")
    
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
                    
                    print(f"  {date_info:<35} {amount_info:<35} [{row['bank_name']}] {row['bank_description'][:40]}")
        
        total_deposits = df_matched[df_matched['direction'] == 'DEPOSIT']['sec_amount'].sum()
        total_withdrawals = df_matched[df_matched['direction'] == 'WITHDRAWAL']['sec_amount'].sum()
        net_investment = total_deposits - total_withdrawals
        
        print("\n" + "=" * 100)
        print(f"💰 TOTAL DEPOSITS:     {total_deposits:>15,.0f} KRW")
        print(f"💸 TOTAL WITHDRAWALS:  {total_withdrawals:>15,.0f} KRW")
        print(f"📊 NET INVESTMENT:     {net_investment:>15,.0f} KRW")
        print("=" * 100)
    
    if len(df_unmatched_sec) > 0:
        print("\n" + "=" * 100)
        print(f"⚠️  UNMATCHED SECURITIES TRANSACTIONS ({len(df_unmatched_sec)})")
        print("=" * 100)
        
        for direction in ['DEPOSIT', 'WITHDRAWAL']:
            df_dir = df_unmatched_sec[df_unmatched_sec['direction'] == direction]
            if len(df_dir) > 0:
                print(f"\n{direction}S:")
                for _, row in df_dir.head(20).iterrows():
                    print(f"  {row['date'].strftime('%Y-%m-%d')}  {row['amount']:>12,.0f}원  {row['type']:<20}")
                if len(df_dir) > 20:
                    print(f"  ... and {len(df_dir) - 20} more")
    
    if len(df_unmatched_bank) > 0:
        print("\n" + "=" * 100)
        print(f"⚠️  UNMATCHED BANK TRANSACTIONS ({len(df_unmatched_bank)})")
        print("=" * 100)
        
        for direction in ['DEPOSIT', 'WITHDRAWAL']:
            df_dir = df_unmatched_bank[df_unmatched_bank['direction'] == direction]
            if len(df_dir) > 0:
                print(f"\n{direction}S:")
                for _, row in df_dir.head(20).iterrows():
                    print(f"  {row['date'].strftime('%Y-%m-%d')}  {row['amount']:>12,.0f}원  [{row['bank']}] {row['description']}")
                if len(df_dir) > 20:
                    print(f"  ... and {len(df_dir) - 20} more")


def main():
    print("🚀 Starting cashflow matching with actual bank files\n")
    
    df_securities = load_securities_cashflows()
    df_bank = load_all_bank_transactions()
    
    if len(df_bank) == 0:
        print("\n❌ No bank transactions found!")
        return 1
    
    df_matched, df_unmatched_sec, df_unmatched_bank = match_transactions(
        df_securities,
        df_bank,
        tolerance_days=3,
        tolerance_amount=5000
    )
    
    print_results(df_matched, df_unmatched_sec, df_unmatched_bank)
    
    output_file = REPO_ROOT / "cashflow_matching_report_bank_files.csv"
    df_matched.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 Detailed results saved to: {output_file}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
