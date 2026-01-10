
import os
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.append(os.getcwd())

from backend.services.duckdb_refine import refine_portfolio_for_ai

def check_refinement():
    print("=== DuckDB Refinement Output Check ===")
    
    # Run for 2026 (current year in system time)
    try:
        refined = refine_portfolio_for_ai(year=2026)
        
        # Structure check
        print(f"Refined by: {refined.get('refined_by')}")
        print(f"Period: {refined.get('period', {}).get('label')}")
        
        print("\n[Portfolio Summary]")
        summary = refined.get('portfolio_summary', {})
        for k, v in summary.items():
            if not k.startswith('_'):
                print(f" - {k}: {v}")
                
        print("\n[Category Breakdown]")
        categories = refined.get('category_breakdown', [])
        for cat in categories[:5]: # Show top 5
            print(f" - {cat['category']}: {cat['total_value']:,} ({cat['weight_pct']}%)")
            
        print("\n[Asset Analytics (Top 3)]")
        assets = refined.get('asset_analytics', [])
        for asset in assets[:3]:
            print(f" - {asset['name']} ({asset['ticker']}): {asset['current_value']:,}")
            
        print("\n[Expense Summary]")
        expense = refined.get('expense_summary', {})
        print(f" - Total Income: {expense.get('total_income', 0):,}")
        print(f" - Total Spending: {expense.get('total_spending', 0):,}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_refinement()
