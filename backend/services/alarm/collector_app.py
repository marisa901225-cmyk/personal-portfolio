import logging
import os
import json
from typing import Optional
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
# services/alarm/ 위치에서 상위로 이동하여 storage 접근
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "storage/db/portfolio.db")
API_TOKEN = os.getenv("API_TOKEN")

class AlarmPayload(BaseModel):
    raw_text: str
    sender: Optional[str] = None
    app_name: Optional[str] = None
    package: Optional[str] = None
    app_title: Optional[str] = None
    conversation: Optional[str] = None
    received_at: Optional[str] = None

@app.post("/webhook")
async def collect_alarm(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    Tasker로부터 알림을 수신하여 DB에 저장한다. (Service Layer 호출)
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
        try:
            data = await request.json()
        except Exception:
            body_bytes = await request.body()
            body_str = body_bytes.decode("utf-8")
            if body_str.startswith('"') and body_str.endswith('"'):
                body_str = json.loads(body_str, strict=False)
            data = json.loads(body_str, strict=False)
        
        payload = AlarmPayload(**data)
        
    except Exception as e:
        logger.error(f"JSON Parsing Error: {e}")
        raise HTTPException(status_code=422, detail=f"Invalid JSON format: {str(e)}")

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
    
    return result

@app.get("/health")
def health_check():
    return {"status": "running"}
