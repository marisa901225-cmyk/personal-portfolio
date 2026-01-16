import logging
from datetime import datetime
from contextlib import contextmanager, asynccontextmanager
from sqlalchemy.orm import Session
from ..core.models import SchedulerState

logger = logging.getLogger(__name__)


@contextmanager
def monitor_job(job_id: str, db: Session):
    """
    스케줄러 작업의 실행 상태를 DB에 기록하는 컨텍스트 매니저 (Sync).
    """
    state = db.query(SchedulerState).filter(SchedulerState.job_id == job_id).first()
    if not state:
        state = SchedulerState(job_id=job_id)
        db.add(state)

    state.status = "running"
    state.last_run_at = datetime.utcnow()
    state.message = None
    db.commit()

    try:
        yield
        state.status = "success"
        state.last_success_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        state.status = "failure"
        state.last_failure_at = datetime.utcnow()
        state.message = str(e)
        db.commit()
        logger.exception("Scheduler job failed: %s", job_id)
        raise


@asynccontextmanager
async def monitor_job_async(job_id: str, db: Session):
    """
    스케줄러 작업의 실행 상태를 DB에 기록하는 컨텍스트 매니저 (Async).
    """
    state = db.query(SchedulerState).filter(SchedulerState.job_id == job_id).first()
    if not state:
        state = SchedulerState(job_id=job_id)
        db.add(state)

    state.status = "running"
    state.last_run_at = datetime.utcnow()
    state.message = None
    db.commit()

    try:
        yield
        state.status = "success"
        state.last_success_at = datetime.utcnow()
        db.commit()
    except Exception as e:
        state.status = "failure"
        state.last_failure_at = datetime.utcnow()
        state.message = str(e)
        db.commit()
        logger.exception("Scheduler job failed: %s", job_id)
        raise
