
import time
import os
import sys

# Add backend to path
sys.path.append(os.path.abspath("backend"))

from backend.core.db import SessionLocal
from backend.core.models import Asset, Trade, ExternalCashflow, User
from backend.services.portfolio import calculate_summary, to_asset_read, to_trade_read
from sqlalchemy.orm import Session


def profile_all():
    db = SessionLocal()
    try:
        user = db.query(User).first()
        
        # --- /api/portfolio ---
        print("\n--- Testing /api/portfolio ---")
        start_total = time.time()
        assets = db.query(Asset).filter(Asset.user_id == user.id, Asset.deleted_at.is_(None)).all()
        trades = db.query(Trade).filter(Trade.user_id == user.id).limit(50).all()
        external_cashflows = db.query(ExternalCashflow).filter(ExternalCashflow.user_id == user.id).all()
        summary = calculate_summary(assets, external_cashflows)
        print(f"Portfolio done: {time.time() - start_total:.4f}s")

        # --- /api/portfolio/snapshots ---
        print("\n--- Testing /api/portfolio/snapshots ---")
        start = time.time()
        from backend.core.models import PortfolioSnapshot
        from datetime import datetime, timedelta
        since = datetime.utcnow() - timedelta(days=365)
        snapshots = db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.user_id == user.id,
            PortfolioSnapshot.snapshot_at >= since
        ).all()
        print(f"Snapshots fetch ({len(snapshots)}): {time.time() - start:.4f}s")
        
        # --- /api/cashflows ---
        print("\n--- Testing /api/cashflows ---")
        start = time.time()
        cfs = db.query(ExternalCashflow).filter(ExternalCashflow.user_id == user.id).all()
        print(f"Cashflows fetch ({len(cfs)}): {time.time() - start:.4f}s")

    finally:
        db.close()

if __name__ == "__main__":
    profile_all()
