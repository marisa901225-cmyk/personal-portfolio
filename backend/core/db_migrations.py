from __future__ import annotations

import logging
from sqlalchemy import inspect, text, Connection
from .db import engine
from .models import Base

logger = logging.getLogger(__name__)

def ensure_schema() -> None:
    """
    모든 테이블의 스키마를 최신 상태로 유지한다.
    Base.metadata.create_all로 테이블을 생성하고, 
    이후 추가된 컬럼들을 하나의 트랜잭션 내에서 안전하게 마이그레이션한다.
    """
    try:
        # 1. 소속 테이블 생성 (이미 있으면 무시)
        Base.metadata.create_all(bind=engine)
        
        # 2. 컬럼 마이그레이션 수행 (단일 트랜잭션 보장 💖)
        with engine.begin() as conn:
            logger.info("[Migration] Starting unified schema migration...")
            
            _migrate_settings_table(conn)
            _migrate_assets_table(conn)
            _migrate_expenses_table(conn)
            
            logger.info("[Migration] All migrations completed successfully.")
            
    except Exception as e:
        logger.error(f"[Migration] Schema migration failed: {e}")
        # engine.begin()이 예외 발생 시 자동으로 롤백을 수행함 (도라의 걱정 해결! 💖)
        raise e


def _migrate_settings_table(conn: Connection) -> None:
    """settings 테이블 컬럼 추가"""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("settings")}

    statements: list[str] = []
    
    # 배당금 관련
    if "dividend_year" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividend_year INTEGER")
    if "dividend_total" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividend_total FLOAT")
    if "dividends" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN dividends JSON")
    
    # 환율 관련
    if "usd_fx_base" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN usd_fx_base FLOAT")
    if "usd_fx_now" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN usd_fx_now FLOAT")
    
    # 벤치마크 관련
    if "benchmark_name" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN benchmark_name VARCHAR(100)")
    if "benchmark_return" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN benchmark_return FLOAT")
    if "benchmark_updated_at" not in columns:
        statements.append("ALTER TABLE settings ADD COLUMN benchmark_updated_at DATETIME")
    
    # KIS API 설정 관련
    kis_configs = [
        ("kis_app", "VARCHAR(128)"), ("kis_sec", "VARCHAR(128)"),
        ("kis_acct_stock", "VARCHAR(64)"), ("kis_prod", "VARCHAR(8)"),
        ("kis_htsid", "VARCHAR(64)"), ("kis_prod_url", "VARCHAR(255)"),
        ("kis_ops_url", "VARCHAR(255)"), ("kis_vps_url", "VARCHAR(255)"),
        ("kis_vops_url", "VARCHAR(255)"), ("kis_agent", "VARCHAR(128)"),
        ("kis_token_encrypted", "TEXT"), ("kis_token_expires_at", "DATETIME")
    ]
    
    for col_name, col_type in kis_configs:
        if col_name not in columns:
            statements.append(f"ALTER TABLE settings ADD COLUMN {col_name} {col_type}")

    for stmt in statements:
        logger.info(f"[Migration] Executing: {stmt}")
        conn.execute(text(stmt))


def _migrate_assets_table(conn: Connection) -> None:
    """assets 테이블 컬럼 추가"""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("assets")}

    if "cma_config" not in columns:
        stmt = "ALTER TABLE assets ADD COLUMN cma_config JSON"
        logger.info(f"[Migration] Executing: {stmt}")
        conn.execute(text(stmt))


def _migrate_expenses_table(conn: Connection) -> None:
    """expenses 테이블 컬럼 추가"""
    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("expenses")}

    if "deleted_at" not in columns:
        stmt = "ALTER TABLE expenses ADD COLUMN deleted_at DATETIME"
        logger.info(f"[Migration] Executing: {stmt}")
        conn.execute(text(stmt))
