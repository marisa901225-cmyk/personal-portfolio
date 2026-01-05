#!/usr/bin/env python3
"""
Import 2025 transactions from combined_statements_valuation.xlsx into portfolio.db

This script reads normalized transaction data from the Excel file and imports:
1. Trades (buy/sell transactions)
2. External cashflows (deposits/withdrawals)
3. FX transactions (currency exchanges)
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Database setup
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "backend" / "portfolio.db"
EXCEL_PATH = REPO_ROOT / "combined_statements_valuation.xlsx"

engine = create_engine(f"sqlite:///{DB_PATH}")
Session = sessionmaker(bind=engine)


def get_user_id(session):
    """Get the first user ID (assuming single user system)"""
    result = session.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 1"))
    row = result.fetchone()
    return row[0] if row else None


def normalize_ticker(symbol_name: str, exchange: str = None) -> str:
    """
    Normalize symbol names to match the portfolio system format.
    
    Korean stocks: 6-digit code
    US stocks: EXCD:SYMB format (e.g., NYS:SPY, NAS:QQQ)
    """
    if not symbol_name or pd.isna(symbol_name):
        return None
    
    # Map common stock names to tickers
    mappings = {
        "ACE 미국S&P500": "441680",
        "State Street SPDR S&P 500 ETF": "NYS:SPY",
        "ProShares QQQ 2배 ETF": "NAS:QLD",
        "Vanguard Total Bond Market Index Fund ETF": "NAS:BND",
    }
    
    return mappings.get(symbol_name, symbol_name)


def import_trades(session, df_2025, user_id):
    """Import buy/sell trades from the Excel data"""
    print("\n📊 Importing trades...")
    
    # Filter for buy/sell transactions only
    trade_types = ['매수', '매도', '미국(NASDAQ)주식매수', '미국(NYSE)주식매수', 
                   '미국(NASDAQ)주식매도', '미국(NYSE)주식매도', 
                   'Smart+거래소주식매수', 'Smart+거래소주식매도',
                   '매수_NXT', '매도_NXT']
    
    df_trades = df_2025[df_2025['거래구분'].isin(trade_types)].copy()
    
    imported = 0
    skipped = 0
    
    for idx, row in df_trades.iterrows():
        # Skip if no stock name
        if pd.isna(row['종목명']) or not row['종목명']:
            skipped += 1
            continue
            
        # Determine trade type
        trade_type = 'BUY' if '매수' in row['거래구분'] else 'SELL'
        
        # Get quantity and price
        quantity = float(row['거래수량']) if pd.notna(row['거래수량']) else 0
        if quantity == 0:
            skipped += 1
            continue
            
        # For sells, quantity should be positive
        if trade_type == 'SELL':
            quantity = abs(quantity)
        
        # Calculate price from 거래금액 / 거래수량
        # 거래단가 is always NaN in the data, so we calculate it
        trade_amount = float(row['거래금액']) if pd.notna(row['거래금액']) else 0
        if trade_amount > 0 and quantity > 0:
            price = trade_amount / quantity
        else:
            price = 0
        
        # Get or create asset
        ticker = normalize_ticker(row['종목명'])
        if not ticker:
            skipped += 1
            continue
            
        # Check if asset exists
        asset_query = text("""
            SELECT id FROM assets 
            WHERE user_id = :user_id AND (ticker = :ticker OR name = :name)
            AND deleted_at IS NULL
            LIMIT 1
        """)
        result = session.execute(asset_query, {
            "user_id": user_id,
            "ticker": ticker,
            "name": row['종목명']
        })
        asset_row = result.fetchone()
        
        if not asset_row:
            print(f"  ⚠️  Asset not found: {row['종목명']} ({ticker}), skipping trade")
            skipped += 1
            continue
        
        asset_id = asset_row[0]
        
        # Insert trade
        timestamp = pd.to_datetime(row['거래일자']).to_pydatetime()  # Convert to Python datetime
        
        insert_query = text("""
            INSERT INTO trades 
            (user_id, asset_id, type, quantity, price, timestamp, created_at, updated_at)
            VALUES 
            (:user_id, :asset_id, :type, :quantity, :price, :timestamp, :now, :now)
        """)
        
        session.execute(insert_query, {
            "user_id": user_id,
            "asset_id": asset_id,
            "type": trade_type,
            "quantity": quantity,
            "price": price,
            "timestamp": timestamp,
            "now": datetime.now()
        })
        
        imported += 1
    
    session.commit()
    print(f"  ✅ Imported {imported} trades, skipped {skipped}")
    return imported


def import_cashflows(session, df_2025, user_id):
    """Import deposits/withdrawals as external cashflows"""
    print("\n💰 Importing cashflows...")
    
    # Cashflow types (입금 = deposit = negative, 출금 = withdrawal = positive in XIRR convention)
    deposit_types = ['타사이체입금', '이체입금', '대체입금', '배당금입금', 
                     'ETF분배금입금', '이용료입금', '외화배당세금환급']
    withdrawal_types = ['실시간자동출금', '대체출금', 'Smart+타사이체출금', 
                       'Smart+당사이체출금', '이체출금', '오픈이체출금']
    
    df_cashflows = df_2025[df_2025['거래구분'].isin(deposit_types + withdrawal_types)].copy()
    
    imported = 0
    
    for idx, row in df_cashflows.iterrows():
        # Skip배당금 (dividends) - these should be tracked separately
        description = row['거래구분']
        if '배당' in description or 'DIV' in str(description).upper():
            # Dividends are tracked in trades table with type='DIVIDEND'
            continue
        
        # Determine amount (XIRR convention: negative for deposits, positive for withdrawals)
        if row['거래구분'] in deposit_types:
            amount = -abs(float(row['정산금액'])) if pd.notna(row['정산금액']) else 0
        else:
            amount = abs(float(row['정산금액'])) if pd.notna(row['정산금액']) else 0
        
        if amount == 0:
            continue
        
        date = pd.to_datetime(row['거래일자']).date()
        
        insert_query = text("""
            INSERT INTO external_cashflows 
            (user_id, date, amount, description, created_at, updated_at)
            VALUES 
            (:user_id, :date, :amount, :description, :now, :now)
        """)
        
        session.execute(insert_query, {
            "user_id": user_id,
            "date": date,
            "amount": amount,
            "description": description,
            "now": datetime.now()
        })
        
        imported += 1
    
    session.commit()
    print(f"  ✅ Imported {imported} cashflows")
    return imported


def import_fx_transactions(session, df_2025, user_id):
    """Import currency exchange transactions"""
    print("\n💱 Importing FX transactions...")
    
    fx_types = ['외화매수', '외화매도', '자동환전(외화매수)', '시간외 외화매도']
    df_fx = df_2025[df_2025['거래구분'].isin(fx_types)].copy()
    
    imported = 0
    
    for idx, row in df_fx.iterrows():
        currency = row['통화코드'] if pd.notna(row['통화코드']) else 'USD'
        
        # Determine type (BUY or SELL)
        trans_type = 'SELL' if '매도' in row['거래구분'] else 'BUY'
        
        # For FX, amount_from is KRW, amount_to is foreign currency
        krw_amount = abs(float(row['정산금액'])) if pd.notna(row['정산금액']) else 0
        fx_amount = abs(float(row['외화정산금액'])) if pd.notna(row['외화정산금액']) else 0
        
        if krw_amount == 0 and fx_amount == 0:
            continue
        
        # Calculate exchange rate
        if fx_amount > 0 and krw_amount > 0:
            rate = krw_amount / fx_amount
        elif pd.notna(row['환율']):
            rate = float(row['환율'])
        else:
            rate = 1200.0  # Default USD/KRW rate
        
        trade_date = pd.to_datetime(row['거래일자']).date()
        description = row['거래구분']
        
        insert_query = text("""
            INSERT INTO fx_transactions 
            (user_id, trade_date, type, currency, 
             fx_amount, krw_amount, rate, description,
             created_at, updated_at)
            VALUES 
            (:user_id, :trade_date, :type, :currency,
             :fx_amount, :krw_amount, :rate, :description,
             :now, :now)
        """)
        
        session.execute(insert_query, {
            "user_id": user_id,
            "trade_date": trade_date,
            "type": trans_type,
            "currency": currency,
            "fx_amount": fx_amount,
            "krw_amount": krw_amount,
            "rate": rate,
            "description": description,
            "now": datetime.now()
        })
        
        imported += 1
    
    session.commit()
    print(f"  ✅ Imported {imported} FX transactions")
    return imported


def main():
    print("🚀 Starting 2025 data import from combined_statements_valuation.xlsx")
    print(f"   Excel file: {EXCEL_PATH}")
    print(f"   Database: {DB_PATH}")
    
    if not EXCEL_PATH.exists():
        print(f"❌ Error: Excel file not found at {EXCEL_PATH}")
        return 1
    
    if not DB_PATH.exists():
        print(f"❌ Error: Database not found at {DB_PATH}")
        return 1
    
    # Read Excel file
    print("\n📖 Reading Excel file...")
    xls = pd.ExcelFile(EXCEL_PATH)
    df = pd.read_excel(xls, sheet_name='All_Normalized')
    
    # Convert date column
    df['거래일자'] = pd.to_datetime(df['거래일자'], errors='coerce')
    
    # Filter for 2025
    df_2025 = df[df['거래일자'].dt.year == 2025].copy()
    print(f"   Found {len(df_2025)} transactions in 2025")
    
    # Create session
    session = Session()
    
    try:
        # Get user ID
        user_id = get_user_id(session)
        if not user_id:
            print("❌ Error: No user found in database")
            return 1
        
        print(f"   User ID: {user_id}")
        
        # Import data
        trades_count = import_trades(session, df_2025, user_id)
        cashflows_count = import_cashflows(session, df_2025, user_id)
        fx_count = import_fx_transactions(session, df_2025, user_id)
        
        print("\n✅ Import completed successfully!")
        print(f"   Trades: {trades_count}")
        print(f"   Cashflows: {cashflows_count}")
        print(f"   FX transactions: {fx_count}")
        
    except Exception as e:
        print(f"\n❌ Error during import: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return 1
    finally:
        session.close()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
