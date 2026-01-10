"""
DuckDB-based analytical data refinement service (compat wrapper).

실제 구현은 duckdb_refine_core에 두고, 기존 import 경로를 유지한다.
"""
from .duckdb_refine_config import get_db_path
from .duckdb_refine_core import refine_portfolio_for_ai

__all__ = ["get_db_path", "refine_portfolio_for_ai"]
