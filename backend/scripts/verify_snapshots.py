#!/usr/bin/env python3
"""
스냅샷 검증 스크립트 - 전체 포트폴리오 검증
- KIS API로 과거 시세를 조회하여 스냅샷 데이터와 비교
"""

import sys
import sqlite3
from pathlib import Path

# Add KIS module path
repo_root = Path(__file__).resolve().parents[2]
kis_modules = repo_root / "backend" / "integrations" / "kis" / "open_trading"
if str(kis_modules) not in sys.path:
    sys.path.insert(0, str(kis_modules))

import kis_auth as ka
import pandas as pd
from datetime import datetime

# 종목코드 매핑 (DB 자산명 -> KIS 종목코드)
DOMESTIC_TICKERS = {
    "ACE 미국S&P500": "360750",
    "KODEX 미국나스닥100": "379810",
    "ACE 글로벌반도체TOP4 Plus": "446700",
    "TIGER 미국테크TOP10 INDXX": "381170",
    "TIGER 코스닥150바이오테크": "396510",
    "RISE AI&로봇": "448320",
    "ACE 미국달러SOFR금리(합성)": "455760",
}


def fetch_domestic_daily_chart(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """국내주식 일봉 데이터를 조회합니다."""
    ka.auth()
    
    API_URL = "/uapi/domestic-stock/v1/quotations/inquire-daily-price"
    tr_id = "FHKST01010400"
    
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": ticker,
        "FID_INPUT_DATE_1": start_date,
        "FID_INPUT_DATE_2": end_date,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }
    
    res = ka._url_fetch(API_URL, tr_id, "", params)
    
    if res.isOK():
        body = res.getBody()
        output = getattr(body, 'output2', None) or getattr(body, 'output', None)
        if output:
            df = pd.DataFrame(output)
            return df
    
    return pd.DataFrame()


def get_holdings_at_date(conn, target_date: str) -> dict:
    """특정 날짜 기준 보유량 계산 (거래 내역 기반)"""
    query = """
    SELECT a.id, a.name, a.category,
           SUM(CASE WHEN t.type = 'BUY' THEN t.quantity ELSE -t.quantity END) as qty
    FROM assets a
    LEFT JOIN trades t ON a.id = t.asset_id AND t.timestamp <= ?
    WHERE a.deleted_at IS NULL AND a.category != '부동산'
    GROUP BY a.id
    HAVING qty > 0
    """
    df = pd.read_sql_query(query, conn, params=(target_date,))
    return {row['name']: row['qty'] for _, row in df.iterrows()}


def main():
    # DB 연결
    db_path = repo_root / "backend" / "storage" / "db" / "portfolio.db"
    conn = sqlite3.connect(db_path)
    
    # 검증할 날짜: 11월 6일 (최고가 기록일)
    target_date = "2025-11-06"
    
    print(f"=== 스냅샷 검증: {target_date} ===\n")
    
    # 1. DB에서 해당 날짜의 스냅샷 조회
    snap_query = """
    SELECT id, snapshot_at, total_value, total_value - 150000000 as stock_value
    FROM portfolio_snapshots 
    WHERE date(snapshot_at) = ?
    """
    snap_df = pd.read_sql_query(snap_query, conn, params=(target_date,))
    
    if not snap_df.empty:
        print(f"DB 스냅샷 (id={snap_df.iloc[0]['id']}):")
        print(f"  - 총 자산: {snap_df.iloc[0]['total_value']:,.0f}")
        print(f"  - 주식만: {snap_df.iloc[0]['stock_value']:,.0f}")
    
    # 2. 해당 날짜 보유량 조회
    holdings = get_holdings_at_date(conn, f"{target_date} 23:59:59")
    print(f"\n{target_date} 보유 자산 ({len(holdings)}종목):")
    
    # 3. 국내주식 가격 조회
    total_recalculated = 0
    for name, qty in holdings.items():
        if name in DOMESTIC_TICKERS:
            ticker = DOMESTIC_TICKERS[name]
            df = fetch_domestic_daily_chart(ticker, target_date.replace("-", ""), target_date.replace("-", ""))
            if not df.empty:
                price = int(df.iloc[0]['stck_clpr'])
                value = qty * price
                total_recalculated += value
                print(f"  {name}: {qty}주 × {price:,} = {value:,.0f}")
            else:
                print(f"  {name}: 가격 조회 실패")
        else:
            print(f"  {name}: {qty}주 (해외 또는 매핑 없음)")
    
    print(f"\n국내주식 재계산 합계: {total_recalculated:,.0f}")
    
    conn.close()


if __name__ == "__main__":
    main()
