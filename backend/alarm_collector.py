import logging
import os
import sqlite3
import time
import json
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Header, Request
from pydantic import BaseModel

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("alarm_collector")

app = FastAPI(title="Alarm Collector Service")

# 설정
DB_PATH = os.path.join(os.path.dirname(__file__), "storage/db/portfolio.db")
API_TOKEN = os.getenv("API_TOKEN")

class AlarmPayload(BaseModel):
    raw_text: str
    sender: Optional[str] = None
    app_name: Optional[str] = None
    package: Optional[str] = None
    app_title: Optional[str] = None
    conversation: Optional[str] = None
    received_at: Optional[str] = None

def get_db_connection(max_retries=5, retry_delay=1.0):
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL;")
            return conn
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                logger.warning(f"Database locked, retrying in {retry_delay}s... ({attempt + 1}/{max_retries})")
                time.sleep(retry_delay)
            else:
                raise e
    raise sqlite3.OperationalError("Database is locked after multiple retries")

@app.post("/webhook")
async def collect_alarm(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Tasker로부터 알림을 수신하여 DB에 저장한다. (유연한 JSON 파싱 적용)
    """
    # 1. 인증 검사
    if not API_TOKEN:
        logger.error("API_TOKEN not configured")
        raise HTTPException(status_code=500, detail="Server configuration error")
    
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization.split(" ")[1]
    if token != API_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    # 2. 유연한 바디 파싱
    try:
        # 1차 시도: 표준 JSON 파싱
        try:
            data = await request.json()
        except Exception:
            # 2차 시도: 텍스트로 읽어서 직접 json.loads (Tasker가 문자열로 보낼 경우 대비)
            body_bytes = await request.body()
            body_str = body_bytes.decode("utf-8")
            # strict=False를 사용하여 개행 문자 등 제어 문자 허용
            if body_str.startswith('"') and body_str.endswith('"'):
                body_str = json.loads(body_str, strict=False)
            data = json.loads(body_str, strict=False)
        
        # Pydantic 모델 검증
        payload = AlarmPayload(**data)
        
    except Exception as e:
        body_bytes = await request.body()
        body_str = body_bytes.decode("utf-8")
        logger.error(f"JSON Parsing Error: {e}. Raw body: {body_str}")
        # 상세 디버깅을 위해 에러 메시지 반환
        raise HTTPException(status_code=422, detail=f"Invalid JSON format: {str(e)}")

    # 3. 데이터 정제 (Timestamp 처리)
    received_at_dt = datetime.utcnow()
    if payload.received_at:
        try:
            val = payload.received_at.strip()
            if val.replace('.', '', 1).isdigit():
                received_at_dt = datetime.fromtimestamp(float(val))
        except Exception:
            pass

    # 4. DB 저장
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        conn.execute("PRAGMA busy_timeout = 5000;")
        
        insert_query = """
        INSERT INTO incoming_alarms (
            raw_text, sender, app_name, package, app_title, conversation, status, received_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """
        cursor.execute(insert_query, (
            payload.raw_text, 
            payload.sender, 
            payload.app_name, 
            payload.package, 
            payload.app_title, 
            payload.conversation, 
            received_at_dt
        ))
        conn.commit()
        conn.close()
        
        logger.info(f"Alarm received from {payload.sender}")
        return {"status": "ok", "id": cursor.lastrowid}
        
    except Exception as e:
        logger.error(f"Database Error: {e}")
        raise HTTPException(status_code=500, detail="Database internal error")

@app.get("/health")
def health_check():
    return {"status": "running"}
