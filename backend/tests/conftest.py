import os
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Ensure DATABASE_URL is set to test DB if not already set (fallback)
TEST_DB_PATH = "/home/dlckdgn/personal-portfolio/devplan/test_db/test.db"
if not os.environ.get("DATABASE_URL"):
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

print(f"DEBUG: Using DATABASE_URL={os.environ['DATABASE_URL']}")
