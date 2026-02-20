#!/usr/bin/env python3
"""
Migration script to add esports_matches table for Smart Polling.
Run with: python -m backend.scripts.migrations.add_esports_matches_table
"""
import logging
from sqlalchemy import inspect

from backend.core.db import engine, Base
from backend.core.models import EsportsMatch  # noqa: F401 - ensures model is registered

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "esports_matches" in existing_tables:
        logger.info("Table 'esports_matches' already exists. Skipping.")
        return

    logger.info("Creating 'esports_matches' table...")
    EsportsMatch.__table__.create(engine)
    logger.info("Table 'esports_matches' created successfully!")


if __name__ == "__main__":
    main()
