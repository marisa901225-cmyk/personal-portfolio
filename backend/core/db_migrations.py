from __future__ import annotations

from sqlalchemy import inspect, text

from .db import engine
from .models import Base


def ensure_schema() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_settings_table()
    _migrate_assets_table()
    _migrate_expenses_table()


def _migrate_settings_table() -> None:
    """
    기존 SQLite settings 테이블에 누락된 컬럼(dividend_year, dividend_total, dividends)이 있으면 추가한다.

    - 개인 프로젝트용 간단 마이그레이션이므로, ALTER TABLE만 수행.
    """
    inspector = inspect(engine)
    try:
        columns = {col["name"] for col in inspector.get_columns("settings")}
    except Exception:
        return

    statements: list[str] = []
    if "dividend_year" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividend_year INTEGER")
    if "dividend_total" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividend_total FLOAT")
    if "dividends" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividends JSON")
    if "usd_fx_base" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN usd_fx_base FLOAT")
    if "usd_fx_now" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN usd_fx_now FLOAT")
    if "benchmark_name" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN benchmark_name VARCHAR(100)")
    if "benchmark_return" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN benchmark_return FLOAT")
    if "benchmark_updated_at" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN benchmark_updated_at DATETIME")
    if "kis_app" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_app VARCHAR(128)")
    if "kis_sec" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_sec VARCHAR(128)")
    if "kis_acct_stock" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_acct_stock VARCHAR(64)")
    if "kis_prod" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_prod VARCHAR(8)")
    if "kis_htsid" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_htsid VARCHAR(64)")
    if "kis_prod_url" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_prod_url VARCHAR(255)")
    if "kis_ops_url" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_ops_url VARCHAR(255)")
    if "kis_vps_url" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_vps_url VARCHAR(255)")
    if "kis_vops_url" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_vops_url VARCHAR(255)")
    if "kis_agent" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_agent VARCHAR(128)")
    if "kis_token_encrypted" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_token_encrypted TEXT")
    if "kis_token_expires_at" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN kis_token_expires_at DATETIME")

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def _migrate_assets_table() -> None:
    """
    기존 SQLite assets 테이블에 누락된 컬럼(cma_config)이 있으면 추가한다.
    """
    inspector = inspect(engine)
    try:
        columns = {col["name"] for col in inspector.get_columns("assets")}
    except Exception:
        return

    statements: list[str] = []
    if "cma_config" not in columns:
        statements.append("ALTER TABLE assets ADD COLUMN cma_config JSON")

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))


def _migrate_expenses_table() -> None:
    """
    기존 SQLite expenses 테이블에 누락된 컬럼(deleted_at)이 있으면 추가한다.
    """
    inspector = inspect(engine)
    try:
        columns = {col["name"] for col in inspector.get_columns("expenses")}
    except Exception:
        return

    statements: list[str] = []
    if "deleted_at" not in columns:
        statements.append("ALTER TABLE expenses ADD COLUMN deleted_at DATETIME")

    if not statements:
        return

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
