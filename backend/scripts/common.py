import logging
import os
import sys
from contextlib import contextmanager

from backend.core.db import SessionLocal
from backend.core.logging_config import SensitiveDataFormatter

# Setup logging
def setup_logging(level=logging.INFO):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SensitiveDataFormatter("%(asctime)s [%(levelname)s] %(message)s"))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for existing in root_logger.handlers[:]:
        root_logger.removeHandler(existing)
    root_logger.addHandler(handler)

    # Silence overly verbose loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def confirm_action(msg: str) -> bool:
    """Ask user for confirmation."""
    response = input(f"{msg} (y/N): ").strip().lower()
    return response == "y"
