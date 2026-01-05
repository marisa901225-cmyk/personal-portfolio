
import sys
import os
from pathlib import Path
import json

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from services.duckdb_refine import refine_portfolio_for_ai

try:
    print("Testing refine_portfolio_for_ai...")
    result = refine_portfolio_for_ai(year=2024, month=10)
    print("Successfully refined data.")
    print(json.dumps(result, indent=2, default=str)[:500] + "...")
except Exception as e:
    print(f"Error refining data: {e}")
    sys.exit(1)
