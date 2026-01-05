#!/usr/bin/env python3
"""
Consolidate all financial data into a single Excel file.

This script combines:
1. Securities firm transactions (from combined_statements_valuation.xlsx)
2. Bank transactions (KB, Woori)
3. Card statements (Woori, KB)

Output: consolidated_financial_data.xlsx
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_FILE = PROJECT_DIR / "consolidated_financial_data.xlsx"


def load_securities_data():
    """Load securities transactions"""
    print("📊 Loading securities data...")
    
    file_path = PROJECT_DIR / "combined_statements_valuation.xlsx"
    if not file_path.exists():
        print(f"  ⚠️  File not found: {file_path}")
        return None
    
    df = pd.read_excel(file_path, sheet_name='All_Normalized')
    df['source'] = 'securities'
    df['source_file'] = 'combined_statements_valuation.xlsx'
    
    print(f"  ✅ Loaded {len(df)} securities transactions")
    return df


def load_bank_data():
    """Load bank transactions from multiple files"""
    print("\n🏦 Loading bank data...")
    
    bank_files = {
        'KB_2025': PROJECT_DIR / 'temp_unzipped' / '거래내역조회_20251231.xls',
        'KB_2024': PROJECT_DIR / 'temp_unzipped' / '거래내역조회_20241231.xls',
        'WOORI': PROJECT_DIR / 'temp_unzipped' / 'WOORI.xls',
    }
    
    all_bank_data = []
    
    for bank_name, file_path in bank_files.items():
        if not file_path.exists():
            print(f"  ⚠️  {bank_name}: File not found")
            continue
        
        try:
            # KB bank format
            if 'KB' in bank_name:
                df_raw = pd.read_excel(file_path, skiprows=4)
                df_raw.columns = df_raw.iloc[0]
                df = df_raw[1:].reset_index(drop=True)
                
                df = df.rename(columns={
                    '거래일시': 'date',
                    '적요': 'description',
                    '출금액': 'withdrawal',
                    '입금액': 'deposit',
                    '잔액': 'balance'
                })
            else:  # Woori bank format
                df_raw = pd.read_excel(file_path, skiprows=7)
                df_raw.columns = df_raw.iloc[0]
                df = df_raw[1:].reset_index(drop=True)
                
                df = df.rename(columns={
                    '거래일자': 'date',
                    '거래구분': 'description',
                    '출금(원)': 'withdrawal',
                    '입금(원)': 'deposit',
                    '잔액(원)': 'balance'
                })
            
            # Common processing
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df['withdrawal'] = pd.to_numeric(df['withdrawal'], errors='coerce').fillna(0)
            df['deposit'] = pd.to_numeric(df['deposit'], errors='coerce').fillna(0)
            df['balance'] = pd.to_numeric(df['balance'], errors='coerce')
            
            df['source'] = 'bank'
            df['source_file'] = f'{bank_name}_{file_path.name}'
            df['bank'] = bank_name
            
            all_bank_data.append(df[['date', 'description', 'withdrawal', 'deposit', 'balance', 'source', 'source_file', 'bank']])
            
            print(f"  ✅ {bank_name}: {len(df)} transactions")
        
        except Exception as e:
            print(f"  ❌ {bank_name}: Error - {e}")
    
    if all_bank_data:
        df_combined = pd.concat(all_bank_data, ignore_index=True)
        df_combined = df_combined.sort_values('date', ascending=False).reset_index(drop=True)
        print(f"  📊 Total bank transactions: {len(df_combined)}")
        return df_combined
    
    return None


def load_card_data():
    """Load card statements"""
    print("\n💳 Loading card data...")
    
    card_files = {
        'WOORI_Q1': PROJECT_DIR / 'temp_unzipped' / 'report.xls',
        'WOORI_Q2': PROJECT_DIR / 'temp_unzipped' / 'report (1).xls',
        'WOORI_Q3': PROJECT_DIR / 'temp_unzipped' / 'report (2).xls',
        'WOORI_Q4': PROJECT_DIR / 'temp_unzipped' / 'report (3).xls',
        'KB': PROJECT_DIR / 'temp_unzipped' / '국민카드.xls',
    }
    
    all_card_data = []
    
    for card_name, file_path in card_files.items():
        if not file_path.exists():
            print(f"  ⚠️  {card_name}: File not found")
            continue
        
        try:
            if 'WOORI' in card_name:
                # Woori card format
                df_raw = pd.read_excel(file_path, skiprows=2)
                df = df_raw.copy()
                df.columns = ['date', 'auth_no', 'card', 'merchant', 'business_no', 'type', 'installment', 'amount', 'cancel', 'settle_date']
                
            else:  # KB card format
                # Find header row
                df_raw = pd.read_excel(file_path)
                for i in range(10):
                    row = df_raw.iloc[i]
                    if '이용일' in str(row.values):
                        header_row = i
                        break
                
                df_raw = pd.read_excel(file_path, skiprows=header_row)
                df_raw.columns = df_raw.iloc[0]
                df = df_raw[1:].reset_index(drop=True)
                
                df = df.rename(columns={
                    '이용일': 'date',
                    '이용하신곳': 'merchant',
                    '국내이용금액\n(원)': 'amount'
                })
            
            # Common processing
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df['amount'] = df['amount'].astype(str).str.replace(',', '')
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
            
            df['source'] = 'card'
            df['source_file'] = f'{card_name}_{file_path.name}'
            df['card'] = card_name
            
            # Select common columns
            cols = ['date', 'merchant', 'amount', 'source', 'source_file', 'card']
            df = df[[col for col in cols if col in df.columns]]
            
            all_card_data.append(df)
            
            print(f"  ✅ {card_name}: {len(df)} transactions")
        
        except Exception as e:
            print(f"  ❌ {card_name}: Error - {e}")
    
    if all_card_data:
        df_combined = pd.concat(all_card_data, ignore_index=True)
        df_combined = df_combined.sort_values('date', ascending=False).reset_index(drop=True)
        print(f"  📊 Total card transactions: {len(df_combined)}")
        return df_combined
    
    return None


def main():
    print("🚀 Consolidating all financial data\n")
    print(f"Output file: {OUTPUT_FILE}\n")
    
    # Load all data
    df_securities = load_securities_data()
    df_bank = load_bank_data()
    df_card = load_card_data()
    
    # Create Excel writer
    print(f"\n💾 Writing to {OUTPUT_FILE.name}...")
    
    with pd.ExcelWriter(OUTPUT_FILE, engine='openpyxl') as writer:
        if df_securities is not None:
            df_securities.to_excel(writer, sheet_name='Securities', index=False)
            print(f"  ✅ Securities sheet: {len(df_securities)} rows")
        
        if df_bank is not None:
            df_bank.to_excel(writer, sheet_name='Bank', index=False)
            print(f"  ✅ Bank sheet: {len(df_bank)} rows")
        
        if df_card is not None:
            df_card.to_excel(writer, sheet_name='Card', index=False)
            print(f"  ✅ Card sheet: {len(df_card)} rows")
        
        # Create summary sheet
        summary_data = {
            'Data Type': ['Securities', 'Bank', 'Card'],
            'Row Count': [
                len(df_securities) if df_securities is not None else 0,
                len(df_bank) if df_bank is not None else 0,
                len(df_card) if df_card is not None else 0,
            ],
            'Status': [
                'Loaded' if df_securities is not None else 'Not found',
                'Loaded' if df_bank is not None else 'Not found',
                'Loaded' if df_card is not None else 'Not found',
            ]
        }
        
        df_summary = pd.DataFrame(summary_data)
        df_summary.to_excel(writer, sheet_name='Summary', index=False)
        print(f"  ✅ Summary sheet created")
    
    print(f"\n✅ Consolidation complete!")
    print(f"   Output: {OUTPUT_FILE}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
