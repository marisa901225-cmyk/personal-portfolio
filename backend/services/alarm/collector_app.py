import logging
import os
import json
import asyncio
import sqlite3
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel

from .collector_support import (
    alarm_silence_window_for_now,
    env_int,
    parse_last_seen,
    parse_request_model,
    parse_timestamp,
    require_bearer_token,
)

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("alarm_collector")

# 설정
# services/alarm/ 위치에서 상위로 이동하여 storage 접근
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "storage/db/portfolio.db")
API_TOKEN = os.getenv("API_TOKEN")
CURRENT_HEARTBEAT_STATE_PATH = os.path.join(BASE_DIR, "data/alarm_heartbeat_state.json")
HEARTBEAT_STATE_ARCHIVE_DIR = os.path.join(BASE_DIR, "data/alarm_heartbeat_state_archive")

HEARTBEAT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS device_heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    tailscale_name TEXT,
    ping_target TEXT,
    sent_at DATETIME NOT NULL,
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    battery TEXT,
    charging TEXT,
    network TEXT,
    ping_ok INTEGER,
    alert_sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_device_heartbeats_device_id_id ON device_heartbeats(device_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_device_heartbeats_received_at ON device_heartbeats(received_at);
"""


def _alarm_silence_threshold_seconds() -> int:
    return env_int("ALARM_SILENCE_ALERT_SECONDS", 1800, 60)


def _alarm_silence_check_interval_seconds() -> int:
    return env_int("ALARM_SILENCE_CHECK_SECONDS", 300, 30)


def _heartbeat_silence_threshold_seconds() -> int:
    return env_int("HEARTBEAT_SILENCE_ALERT_SECONDS", 900, 60)


def _heartbeat_retention_days() -> int:
    return env_int("HEARTBEAT_RETENTION_DAYS", 30, 1)


def _new_monitor_state() -> dict:
    return {
        "startup_at": datetime.now(),
        "last_alarm_received_at": None,
        "alert_sent": False,
    }


def _build_alarm_silence_message(silence_seconds: int) -> str:
    silence_minutes = max(1, silence_seconds // 60)
    threshold_minutes = max(1, _alarm_silence_threshold_seconds() // 60)
    return (
        "<b>[알람 수집 경고]</b>\n"
        f"- 휴대폰 알람 수신이 약 {silence_minutes}분째 없습니다.\n"
        f"- 기준 임계값: {threshold_minutes}분\n"
        "- 휴대폰에서 Tailscale 연결이 켜져 있는지 확인해주세요."
    )


def _alarm_silence_window_for_now(now: datetime) -> tuple[bool, Optional[datetime]]:
    return alarm_silence_window_for_now(
        now,
        raw_value=os.getenv("ALARM_SILENCE_ACTIVE_WINDOW", "07:00-23:00"),
    )


def _heartbeat_db_connection(db_path: str, max_retries: int = 5, retry_delay: float = 1.0) -> sqlite3.Connection:
    last_error: Optional[Exception] = None
    for _ in range(max_retries):
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            return conn
        except sqlite3.OperationalError as e:
            last_error = e
            if "locked" in str(e).lower():
                time.sleep(retry_delay)
                continue
            raise
    if last_error:
        raise last_error
    raise sqlite3.OperationalError("database connection failed")


def ensure_heartbeat_table(db_path: str) -> None:
    conn = _heartbeat_db_connection(db_path)
    try:
        conn.executescript(HEARTBEAT_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def cleanup_old_heartbeats(db_path: str) -> None:
    ensure_heartbeat_table(db_path)
    conn = _heartbeat_db_connection(db_path)
    try:
        conn.execute(
            "DELETE FROM device_heartbeats WHERE received_at < datetime('now', ?)",
            (f"-{_heartbeat_retention_days()} days",),
        )
        conn.commit()
    finally:
        conn.close()


def _current_heartbeat_state_path() -> Path:
    return Path(CURRENT_HEARTBEAT_STATE_PATH)


def _heartbeat_archive_dir() -> Path:
    return Path(HEARTBEAT_STATE_ARCHIVE_DIR)


def archive_legacy_heartbeat_state() -> None:
    current_path = _current_heartbeat_state_path()
    if not current_path.exists():
        return

    try:
        payload = json.loads(current_path.read_text(encoding="utf-8"))
    except Exception:
        payload = None

    # 새 포맷(current-only snapshot)이면 그대로 유지
    if isinstance(payload, dict) and payload.get("snapshot_mode") == "current_only":
        return

    archive_dir = _heartbeat_archive_dir() / f"{datetime.now():%Y-%m-%d}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / f"alarm_heartbeat_state_{datetime.now():%H%M%S}.json"
    current_path.replace(archived)


def write_current_heartbeat_state(db_path: str) -> None:
    current_path = _current_heartbeat_state_path()
    current_path.parent.mkdir(parents=True, exist_ok=True)

    devices: dict[str, dict] = {}
    for row in _latest_heartbeat_records(db_path):
        device_id = str(row.get("device_id") or "").strip()
        if not device_id:
            continue
        ping_ok = row.get("ping_ok")
        devices[device_id] = {
            "device_id": device_id,
            "tailscale_name": row.get("tailscale_name"),
            "ping_target": row.get("ping_target"),
            "last_heartbeat_at": row.get("sent_at"),
            "received_at": row.get("received_at"),
            "battery": row.get("battery"),
            "charging": row.get("charging"),
            "network": row.get("network"),
            "ping_ok": None if ping_ok is None else bool(ping_ok),
            "alert_sent": bool(row.get("alert_sent")),
        }

    payload = {
        "snapshot_mode": "current_only",
        "updated_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "retention_days": _heartbeat_retention_days(),
        "devices": devices,
    }
    current_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _latest_heartbeat_records(db_path: str) -> list[dict]:
    ensure_heartbeat_table(db_path)
    conn = _heartbeat_db_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT h.*
            FROM device_heartbeats h
            JOIN (
                SELECT device_id, MAX(id) AS max_id
                FROM device_heartbeats
                GROUP BY device_id
            ) latest
              ON latest.max_id = h.id
            ORDER BY h.device_id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _execute_heartbeat_write(db_path: str, query: str, params: tuple = ()) -> None:
    ensure_heartbeat_table(db_path)
    conn = _heartbeat_db_connection(db_path)
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()
    write_current_heartbeat_state(db_path)


def _record_heartbeat(db_path: str, payload: "HeartbeatPayload") -> None:
    cleanup_old_heartbeats(db_path)
    _execute_heartbeat_write(
        db_path,
        """
        INSERT INTO device_heartbeats (
            device_id, tailscale_name, ping_target, sent_at, battery, charging, network, ping_ok, alert_sent
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0)
        """,
        (
            payload.device_id,
            (payload.tailscale_name or payload.device_id or "").strip(),
            (payload.ping_target or payload.tailscale_name or payload.device_id or "").strip(),
            parse_timestamp(payload.sent_at).isoformat(sep=" ", timespec="seconds"),
            payload.battery,
            payload.charging,
            payload.network,
        ),
    )


def _update_heartbeat_status(db_path: str, row_id: int, *, ping_ok: Optional[bool], alert_sent: bool) -> None:
    _execute_heartbeat_write(
        db_path,
        "UPDATE device_heartbeats SET ping_ok = ?, alert_sent = ? WHERE id = ?",
        (
            None if ping_ok is None else int(bool(ping_ok)),
            int(bool(alert_sent)),
            row_id,
        ),
    )


def _latest_stale_heartbeat_record(db_path: str, now: Optional[datetime] = None) -> Optional[dict]:
    now = now or datetime.now()
    threshold = _heartbeat_silence_threshold_seconds()
    for device in _latest_heartbeat_records(db_path):
        last_at = parse_last_seen(device.get("sent_at"))
        if last_at and (now - last_at).total_seconds() >= threshold:
            return device
    return None


async def _ping_device_target(target: str) -> Optional[bool]:
    target = (target or "").strip()
    if not target:
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            "ping",
            "-c",
            "1",
            "-W",
            "2",
            target,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return (await proc.wait()) == 0
    except Exception:
        logger.exception("Failed to ping heartbeat target")
        return None


def _heartbeat_target(record: dict, device_id: str = "") -> str:
    return record.get("ping_target") or record.get("tailscale_name") or device_id


def _build_heartbeat_alert_message(device_id: str, record: dict, ping_ok: Optional[bool], silence_seconds: int) -> str:
    silence_minutes = max(1, silence_seconds // 60)
    ping_target = _heartbeat_target(record, device_id)
    status_line, hint = {
        True: (
            f"- ping 대상({ping_target})은 응답 중입니다.",
            "- Tasker, 배터리 최적화, HTTP 요청 프로필 상태를 확인해주세요.",
        ),
        False: (
            f"- ping 대상({ping_target})이 응답하지 않습니다.",
            "- 휴대폰 재부팅/안드로이드 업데이트 이후 Tailscale 연결이 내려갔는지 확인해주세요.",
        ),
        None: (
            "- ping 확인은 수행하지 못했습니다.",
            "- 휴대폰 Tailscale, Tasker, 네트워크 상태를 함께 확인해주세요.",
        ),
    }[ping_ok]
    return (
        "<b>[Heartbeat 경고]</b>\n"
        f"- 기기: {device_id}\n"
        f"- heartbeat가 약 {silence_minutes}분째 끊겼습니다.\n"
        f"{status_line}\n"
        f"{hint}"
    )


async def evaluate_heartbeat_silence(now: Optional[datetime] = None) -> bool:
    from ...integrations.telegram import send_telegram_message

    now = now or datetime.now()
    threshold = _heartbeat_silence_threshold_seconds()
    sent_any = False

    for record in _latest_heartbeat_records(DB_PATH):
        device_id = record.get("device_id") or ""
        last_at = parse_last_seen(record.get("sent_at"))
        if last_at is None:
            continue

        silence_seconds = int((now - last_at).total_seconds())
        if silence_seconds < threshold:
            if record.get("alert_sent"):
                _update_heartbeat_status(DB_PATH, int(record["id"]), ping_ok=bool(record["ping_ok"]) if record["ping_ok"] is not None else None, alert_sent=False)
            continue

        if record.get("alert_sent"):
            continue

        ping_ok = await _ping_device_target(_heartbeat_target(record, device_id))
        sent = await send_telegram_message(
            _build_heartbeat_alert_message(device_id, record, ping_ok, silence_seconds),
            bot_type="alarm",
        )
        if sent:
            _update_heartbeat_status(DB_PATH, int(record["id"]), ping_ok=ping_ok, alert_sent=True)
            sent_any = True
    return sent_any


async def evaluate_alarm_silence(
    state: dict,
    db_path: str,
    now: Optional[datetime] = None,
    heartbeat_db_path: Optional[str] = None,
) -> bool:
    from .collector import get_latest_alarm_received_at
    from ...integrations.telegram import send_telegram_message

    now = now or datetime.now()
    in_window, window_start = _alarm_silence_window_for_now(now)
    if not in_window:
        # Quiet hours: don't emit alarm silence alerts.
        # Reset so we can alert again during the next active window.
        state["alert_sent"] = False
        return False

    heartbeat_db_path = heartbeat_db_path or db_path
    state_last_received = state.get("last_alarm_received_at")
    db_last_received = get_latest_alarm_received_at(db_path)

    last_received = state_last_received
    if db_last_received and (last_received is None or db_last_received > last_received):
        last_received = db_last_received
        state["alert_sent"] = False

    if last_received is None:
        last_received = state.setdefault("startup_at", now)

    state["last_alarm_received_at"] = last_received

    effective_last_received = last_received
    if window_start is not None and effective_last_received < window_start:
        # If the last alarm is before today's active window, only measure silence
        # inside the active window to prevent noisy "overnight silence" alerts.
        effective_last_received = window_start

    silence_seconds = int((now - effective_last_received).total_seconds())
    if silence_seconds < _alarm_silence_threshold_seconds():
        state["alert_sent"] = False
        return False

    stale_heartbeat = _latest_stale_heartbeat_record(heartbeat_db_path, now)
    if stale_heartbeat is None:
        return False

    ping_ok = await _ping_device_target(_heartbeat_target(stale_heartbeat, stale_heartbeat.get("device_id") or ""))
    if ping_ok is not False:
        return False

    if state.get("alert_sent"):
        return False

    sent = await send_telegram_message(
        _build_alarm_silence_message(silence_seconds),
        bot_type="alarm",
    )
    if sent:
        state["alert_sent"] = True
    return sent


async def _alarm_silence_monitor_loop() -> None:
    while True:
        try:
            await evaluate_heartbeat_silence()
            await evaluate_alarm_silence(_ensure_monitor_state(), DB_PATH)
        except Exception:
            logger.exception("Alarm silence monitor failed")
        await asyncio.sleep(_alarm_silence_check_interval_seconds())


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_heartbeat_table(DB_PATH)
    cleanup_old_heartbeats(DB_PATH)
    archive_legacy_heartbeat_state()
    write_current_heartbeat_state(DB_PATH)
    app.state.alarm_monitor_state = _new_monitor_state()
    task = asyncio.create_task(_alarm_silence_monitor_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Alarm Collector Service", lifespan=lifespan)


def _ensure_monitor_state() -> dict:
    state = getattr(app.state, "alarm_monitor_state", None)
    if state is None:
        state = _new_monitor_state()
        app.state.alarm_monitor_state = state
    return state


class AlarmPayload(BaseModel):
    raw_text: str
    sender: Optional[str] = None
    app_name: Optional[str] = None
    package: Optional[str] = None
    app_title: Optional[str] = None
    conversation: Optional[str] = None
    received_at: Optional[str] = None


class HeartbeatPayload(BaseModel):
    device_id: str
    sent_at: Optional[str] = None
    tailscale_name: Optional[str] = None
    ping_target: Optional[str] = None
    battery: Optional[str] = None
    charging: Optional[str] = None
    network: Optional[str] = None


@app.post("/webhook")
async def collect_alarm(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Tasker로부터 알림을 수신하여 DB에 저장한다. (Service Layer 호출)
    """
    require_bearer_token(API_TOKEN, authorization, logger)
    payload = await parse_request_model(request, AlarmPayload, logger, flexible=True)

    # 3. 서비스 레이어 호출
    from .collector import collect_alarm_logic
    
    result = await collect_alarm_logic(
        db_path=DB_PATH,
        raw_text=payload.raw_text,
        sender=payload.sender,
        app_name=payload.app_name,
        package=payload.package,
        app_title=payload.app_title,
        conversation=payload.conversation,
        received_at=payload.received_at
    )

    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result["message"])

    if result["status"] == "ok":
        _ensure_monitor_state().update(
            last_alarm_received_at=datetime.now(),
            alert_sent=False,
        )
    
    return result


@app.post("/heartbeat")
async def collect_heartbeat(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    require_bearer_token(API_TOKEN, authorization, logger)
    payload = await parse_request_model(request, HeartbeatPayload, logger)
    _record_heartbeat(DB_PATH, payload)

    return {"status": "ok", "device_id": payload.device_id}


@app.get("/health")
def health_check():
    return {"status": "running"}
