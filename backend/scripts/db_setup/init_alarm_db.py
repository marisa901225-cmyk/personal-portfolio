import os
import sys
from pathlib import Path

# 프로젝트 루트를 패스에 추가
sys.path.append(os.getcwd())

from backend.core.db import engine, Base
from backend.core.models import * # 모든 모델을 임포트해야 테이블이 생성됨

def init_db():
    print("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")

if __name__ == "__main__":
    init_db()
