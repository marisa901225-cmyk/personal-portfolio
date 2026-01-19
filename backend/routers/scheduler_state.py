from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.models import SchedulerState
from ..core.schemas import SchedulerStateRead

router = APIRouter(prefix="/api/scheduler", tags=["system"], dependencies=[Depends(verify_api_token)])

@router.get("/state", response_model=List[SchedulerStateRead])
def get_scheduler_state(db: Session = Depends(get_db)):
    """
    모든 스케줄러 작업의 실행 상태 및 이력을 조회합니다.
    """
    states = db.query(SchedulerState).order_by(SchedulerState.job_id).all()
    return states
