import logging
import os
import sys
from contextlib import contextmanager

from backend.core.db import SessionLocal

# Setup logging
def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
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
