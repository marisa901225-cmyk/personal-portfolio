import logging
import sqlite3
import time
from datetime import datetime
from typing import Optional
from backend.services.alarm.filters import mask_sensitive_info

logger = logging.getLogger("alarm_collector_service")

def get_db_connection(db_path: str, max_retries=5, retry_delay=1.0):
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL;")
            return conn
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.warning(f"Database locked, retrying in {retry_delay}s... ({attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
            else:
                raise e
    raise sqlite3.OperationalError("Database is locked after multiple retries")

async def collect_alarm_logic(
    db_path: str,
    raw_text: str,
    sender: Optional[str] = None,
    app_name: Optional[str] = None,
    package: Optional[str] = None,
    app_title: Optional[str] = None,
    conversation: Optional[str] = None,
    received_at: Optional[str] = None
) -> dict:
    """
    알림 수신 및 중복 제거, DB 저장 로직 (Service Layer)
    """
    # 1. Timestamp 처리
    received_at_dt = datetime.now()
    if received_at:
        try:
            val = received_at.strip()
            if val.replace('.', '', 1).isdigit():
                received_at_dt = datetime.fromtimestamp(float(val))
        except Exception:
            pass

    # 2. 중복 체크 (3초 이내 동일 내용)
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        
        # 최근 3초 이내에 동일한 raw_text가 있는지 확인
        cursor.execute("""
            SELECT id FROM incoming_alarms 
            WHERE raw_text = ? AND (sender = ? OR app_name = ?)
            AND received_at > datetime('now', '-3 seconds')
            LIMIT 1
        """, (raw_text, sender, app_name))
        
        if cursor.fetchone():
            logger.info("Duplicate alarm detected (within 3s). Skipping.")
            conn.close()
            return {"status": "skipped", "reason": "duplicate"}
            
    except Exception as e:
        logger.warning(f"Deduplication check failed: {e}")

    # 3. DB 저장
    try:
        if 'conn' not in locals() or conn is None:
            conn = get_db_connection(db_path)
            cursor = conn.cursor()

        conn.execute("PRAGMA busy_timeout = 5000;")
        
        insert_query = """
        INSERT INTO incoming_alarms (
            raw_text, masked_text, sender, app_name, package, app_title, conversation, status, received_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """
        cursor.execute(insert_query, (
            raw_text, 
            mask_sensitive_info(raw_text), 
            sender, 
            app_name, 
            package, 
            app_title, 
            conversation, 
            received_at_dt
        ))
        conn.commit()
        last_id = cursor.lastrowid
        conn.close()
        
        logger.info(f"Alarm received and stored (ID: {last_id})")
        return {"status": "ok", "id": last_id}
        
    except Exception as e:
        logger.error(f"Database Error: {e}")
        return {"status": "error", "message": str(e)}
