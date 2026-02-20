import time
import sys
import os
from datetime import date, datetime

# 프로젝트 루트 추가
sys.path.append(os.path.abspath(os.path.join(os.getcwd(), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.core.models import Asset, ExternalCashflow, User
from backend.services.portfolio import calculate_summary

def profile_portfolio():
    # DB 연결
    DB_PATH = "storage/db/portfolio.db"
    engine = create_engine(f"sqlite:///{DB_PATH}")
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        user = db.query(User).first()
        if not user:
            print("No user found")
            return

        print(f"Profiling for user: {user.id}")

        # 데이터 로드 시간 측정
        start_load = time.perf_counter()
        assets = db.query(Asset).filter(Asset.user_id == user.id).all()
        cashflows = db.query(ExternalCashflow).filter(ExternalCashflow.user_id == user.id).all()
        end_load = time.perf_counter()
        print(f"DB Load Time: {end_load - start_load:.4f}s (Assets: {len(assets)}, Cashflows: {len(cashflows)})")

        # 계산 시간 측정
        start_calc = time.perf_counter()
        summary = calculate_summary(assets, cashflows)
        end_calc = time.perf_counter()
        print(f"Calculation Time (inc. XIRR): {end_calc - start_calc:.4f}s")
        print(f"XIRR Value: {summary.xirr_rate}")

    finally:
        db.close()

if __name__ == "__main__":
    profile_portfolio()
