
import os
import sys
import logging
from datetime import datetime

# 프로젝트 루트를 패스에 추가
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from backend.core.db import SessionLocal, engine
from backend.core.models import GameNews, SpamNews
from sqlalchemy import func

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deduplicate_cleanup")

def cleanup_table(db, model, table_name):
    logger.info(f"Starting duplicate cleanup for {table_name}...")
    
    # 1. 제목 기준 중복 제거
    duplicate_titles = (
        db.query(model.title)
        .group_by(model.title)
        .having(func.count(model.id) > 1)
        .all()
    )
    
    logger.info(f"Found {len(duplicate_titles)} titles with duplicates in {table_name}.")
    
    total_deleted = 0
    for (title,) in duplicate_titles:
        ids = [r[0] for r in db.query(model.id).filter(model.title == title).order_by(model.id.asc()).all()]
        if len(ids) > 1:
            to_delete = ids[1:]
            deleted = db.query(model).filter(model.id.in_(to_delete)).delete(synchronize_session=False)
            total_deleted += deleted
            if total_deleted % 1000 == 0:
                db.commit()
                logger.info(f"Deleted {total_deleted} items from {table_name}...")

    db.commit()
    logger.info(f"Total {total_deleted} duplicate items deleted from {table_name} (title-based).")

    # 2. content_hash 기준 중복 제거
    duplicate_hashes = (
        db.query(model.content_hash)
        .group_by(model.content_hash)
        .having(func.count(model.id) > 1)
        .all()
    )
    logger.info(f"Found {len(duplicate_hashes)} hashes with duplicates in {table_name}.")
    
    hash_deleted = 0
    for (h,) in duplicate_hashes:
        ids = [r[0] for r in db.query(model.id).filter(model.content_hash == h).order_by(model.id.asc()).all()]
        if len(ids) > 1:
            to_delete = ids[1:]
            deleted = db.query(model).filter(model.id.in_(to_delete)).delete(synchronize_session=False)
            hash_deleted += deleted
    
    db.commit()
    logger.info(f"Total {hash_deleted} hash-duplicate items deleted from {table_name}.")

    # 3. 너무 오래된 데이터 삭제 (7일 기준)
    from datetime import timedelta
    threshold = datetime.now() - timedelta(days=7)
    old_deleted = (
        db.query(model)
        .filter(model.published_at < threshold)
        .delete(synchronize_session=False)
    )
    db.commit()
    if old_deleted:
        logger.info(f"Deleted {old_deleted} items older than {threshold} from {table_name}.")

def main():
    logger.info(f"Using Database URL: {engine.url}")
    db = SessionLocal()
    try:
        cleanup_table(db, GameNews, "game_news")
        cleanup_table(db, SpamNews, "spam_news")
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()
