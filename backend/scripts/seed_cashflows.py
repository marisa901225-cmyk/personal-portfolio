#!/usr/bin/env python
"""Insert initial yearly cashflow data"""
import sys
import os

# Add parent directory (backend) to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
sys.path.insert(0, backend_dir)

from db import engine
from models import Base, YearlyCashflow
from services.users import get_or_create_single_user
from sqlalchemy.orm import Session

# Create tables
Base.metadata.create_all(bind=engine)
print('Tables created/verified')

# Insert initial data
with Session(engine) as db:
    user = get_or_create_single_user(db)
    
    # Check if data already exists
    existing = db.query(YearlyCashflow).filter(YearlyCashflow.user_id == user.id).count()
    if existing > 0:
        print(f'Data already exists ({existing} records), skipping')
    else:
        data = [
            YearlyCashflow(user_id=user.id, year=2022, deposit=19360460, withdrawal=4156418, note='초기 자금 형성'),
            YearlyCashflow(user_id=user.id, year=2023, deposit=21982890, withdrawal=2229900),
            YearlyCashflow(user_id=user.id, year=2024, deposit=32219895, withdrawal=3457218, note='외화 입금($5,824.86) 별도'),
            YearlyCashflow(user_id=user.id, year=2025, deposit=29451020, withdrawal=0),
        ]
        db.add_all(data)
        db.commit()
        print('Initial data inserted (4 records)')
