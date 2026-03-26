import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Optional
from backend.services.alarm.filters import mask_sensitive_info

logger = logging.getLogger("alarm_collector_service")


def _dedupe_window_seconds() -> int:
    """중복 알림 판정 윈도우(초). env로 조정 가능."""
    try:
        return max(3, int(os.getenv("ALARM_DEDUP_WINDOW_SECONDS", "1800")))
    except Exception:
        return 1800

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


def _parse_db_datetime(value: object) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("T", " ")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_latest_alarm_received_at(db_path: str) -> Optional[datetime]:
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(received_at) FROM incoming_alarms")
        row = cursor.fetchone()
        return _parse_db_datetime(row[0] if row else None)
    finally:
        conn.close()

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

    # 2. 중복 체크 (기본 30분 이내 동일 시그니처)
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        dedupe_window_seconds = _dedupe_window_seconds()
        dedupe_modifier = f"-{dedupe_window_seconds} seconds"

        sender_norm = (sender or "").strip()
        app_name_norm = (app_name or "").strip()
        package_norm = (package or "").strip()
        app_title_norm = (app_title or "").strip()
        conversation_norm = (conversation or "").strip()

        # 동일 알림 시그니처(raw/app/sender/title/conversation/package)가
        # 최근 일정 시간 내 이미 수집됐으면 중복으로 간주한다.
        cursor.execute("""
            SELECT id FROM incoming_alarms 
            WHERE raw_text = ?
              AND IFNULL(sender, '') = ?
              AND IFNULL(app_name, '') = ?
              AND IFNULL(package, '') = ?
              AND IFNULL(app_title, '') = ?
              AND IFNULL(conversation, '') = ?
              AND received_at >= datetime('now', ?)
            ORDER BY id DESC
            LIMIT 1
        """, (
            raw_text,
            sender_norm,
            app_name_norm,
            package_norm,
            app_title_norm,
            conversation_norm,
            dedupe_modifier,
        ))
        
        if cursor.fetchone():
            logger.info(
                "Duplicate alarm detected (within %ss). Skipping. app=%s sender=%s",
                dedupe_window_seconds,
                app_name_norm or "-",
                sender_norm or "-",
            )
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
