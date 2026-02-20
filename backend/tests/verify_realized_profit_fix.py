import sys
import os
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.core.db import SessionLocal
from backend.core.models import Asset, ExternalCashflow
from backend.services.portfolio import calculate_summary
from backend.services.users import get_or_create_single_user

def verify_fix():
    db = SessionLocal()
    try:
        user = get_or_create_single_user(db)
        # 삭제된 자산 포함 모든 자산 조회 (수정된 라우터 로직과 동일)
        assets = db.query(Asset).filter(Asset.user_id == user.id).all()
        external_cashflows = db.query(ExternalCashflow).filter(ExternalCashflow.user_id == user.id).all()
        
        summary = calculate_summary(assets, external_cashflows)
        
        print(f"Total Assets: {len(assets)}")
        print(f"Realized Profit Total: {summary.realized_profit_total}")
        
        # 예상값: 1548806.07590931 (아까 DB에서 직접 확인한 전체 합계)
        expected = 1548806.07590931
        diff = abs(summary.realized_profit_total - expected)
        
        if diff < 0.01:
            print("✅ Verification Successful: Realized profit total matches expected value (including deleted assets).")
        else:
            print(f"❌ Verification Failed: Expected {expected}, but got {summary.realized_profit_total}")
            
    finally:
        db.close()

if __name__ == "__main__":
    verify_fix()
