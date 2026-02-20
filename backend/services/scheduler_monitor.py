import logging
import asyncio
from typing import Callable, Any, Optional
from contextlib import contextmanager, asynccontextmanager
from sqlalchemy.orm import Session
from ..core.models import SchedulerState
from ..core.time_utils import utcnow
from ..integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)


def _notify_failure_sync(job_id: str, error: str):
    """실패 알림 (동기 래퍼: 이벤트 루프 확인 후 태스크 생성)"""
    try:
        msg = f"❌ <b>스케줄러 작업 실패!</b>\n\n<b>Job:</b> {job_id}\n<b>Error:</b> {error[:200]}"
        try:
            # LO의 추천: get_running_loop() 사용으로 더 견고하게! ❤️
            loop = asyncio.get_running_loop()
            loop.create_task(send_telegram_message(msg))
            return
        except RuntimeError:
            # 실행 중인 루프가 없는 경우의 안전한 처리
            logger.warning(f"No running loop found for {job_id} failure notification")
        except Exception as e:
            logger.error(f"Failed to get loop or send message: {e}")
    except Exception as e:
        logger.error(f"Critical error in _notify_failure_sync: {e}")


async def send_service_alert(service_name: str, status: str, error: str = None, restart_count: int = 0, max_restarts: int = 0):
    """
    서비스 상태에 따른 표준 텔레그램 알림을 발송합니다.
    """
    icon = "⚠️" if status == "failure" else "🚨" if status == "stopped" else "ℹ️"
    title = f"<b>[{service_name}] 가동 중단!</b>" if status == "failure" else f"<b>[{service_name}] 최종 중단!</b>"
    
    msg = f"{icon} {title}\n\n"
    if restart_count > 0 or max_restarts > 0:
        msg += f"<b>재시작:</b> {restart_count}/{max_restarts}\n"
    
    if error:
        msg += f"<b>오류:</b> {error[:150]}\n"
    
    if status == "stopped" and max_restarts > 0:
        msg += "\n수동 확인이 필요합니다! ⛔"

    try:
        await send_telegram_message(msg)
    except Exception as e:
        logger.error(f"Failed to send service alert for {service_name}: {e}")


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
    state.last_run_at = utcnow()
    state.message = None
    db.commit()

    try:
        yield
        state.status = "success"
        state.last_success_at = utcnow()
        db.commit()
    except Exception as e:
        # LO의 추천: 트랜잭션 안전을 위해 롤백! ❤️
        db.rollback()
        
        state.status = "failure"
        state.last_failure_at = utcnow()
        state.message = str(e)
        db.commit()
        logger.exception("Scheduler job failed: %s", job_id)
        _notify_failure_sync(job_id, str(e))
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
    state.last_run_at = utcnow()
    state.message = None
    db.commit()

    try:
        yield
        state.status = "success"
        state.last_success_at = utcnow()
        db.commit()
    except Exception as e:
        # LO의 추천: 트랜잭션 안전을 위해 롤백! ❤️
        db.rollback()
        
        state.status = "failure"
        state.last_failure_at = utcnow()
        state.message = str(e)
        db.commit()
        logger.exception("Scheduler job failed: %s", job_id)
        
        # Notify via Telegram
        try:
            await send_telegram_message(
                f"❌ <b>스케줄러 작업 실패!</b>\n\n<b>Job:</b> {job_id}\n<b>Error:</b> {str(e)[:200]}"
            )
        except:
            pass
        raise


def update_scheduler_state(job_id: str, db: Session, status: str, message: str = None):
    """
    특정 서비스나 작업의 상태를 명시적으로 업데이트합니다.
    """
    state = db.query(SchedulerState).filter(SchedulerState.job_id == job_id).first()
    if not state:
        state = SchedulerState(job_id=job_id)
        db.add(state)

    state.status = status
    state.last_run_at = utcnow()
    if status == "success":
        state.last_success_at = utcnow()
    elif status == "failure":
        state.last_failure_at = utcnow()
    
    if message:
        state.message = message
        
    db.commit()


async def run_with_monitoring(service_name: str, func: Callable, db_factory: Callable, *args, **kwargs):
    """
    태스크를 실행하고 상태를 기록하며 예외 발생 시 알림을 보냅니다.
    (Execution -> Record -> Notify)
    """
    with db_factory() as db:
        try:
            logger.info(f"[{service_name}] Task starting...")
            update_scheduler_state(service_name, db, "running")
            
            # [FIXED] Support both coroutine functions and functions returning awaitables (e.g. lambdas)
            import inspect
            res = func(*args, **kwargs)
            if inspect.isawaitable(res):
                await res

            logger.info(f"[{service_name}] Task finished successfully")
            update_scheduler_state(service_name, db, "success", "Finished normally")
            return True

        except Exception as e:
            # LO의 추천: 여기도 롤백으로 안전하게! ❤️
            db.rollback()
            
            error_msg = str(e)
            logger.error(f"[{service_name}] Task failed: {error_msg}", exc_info=True)
            update_scheduler_state(service_name, db, "failure", error_msg)
            # Notify but let the caller handle restart policy
            return e
