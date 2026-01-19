"""
KIS API 서킷브레이커 및 분산 락 관리 모듈

- 토큰 갱신 스탬피드 방지를 위한 DB 기반 분산 락
- 연속 실패 시 서킷브레이커로 발급 시도 자체를 차단
- 지수 백오프로 재시도 간격 조절
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from ...core.db import SessionLocal
from ...core.models import Setting
from ...services.users import get_or_create_single_user

logger = logging.getLogger(__name__)

# 설정 상수
LOCK_TIMEOUT_SEC = 60  # 락 타임아웃 (교착 방지)
FAILURE_THRESHOLD = 5  # 서킷 오픈 조건
CIRCUIT_OPEN_DURATION_SEC = 300  # 5분
MAX_BACKOFF_SEC = 60
REFRESH_WINDOW_HOURS = 2  # 만료 2시간 전부터 갱신 시도
HARD_EXPIRY_BUFFER_HOURS = 0.5  # 만료 30분 전까지는 기존 토큰 사용 가능


def _get_setting(db: Session) -> Setting:
    """Setting 객체 조회 (없으면 생성)"""
    user = get_or_create_single_user(db)
    setting = (
        db.query(Setting)
        .filter(Setting.user_id == user.id)
        .order_by(Setting.id.asc())
        .first()
    )
    if setting:
        return setting
    setting = Setting(user_id=user.id)
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


# ============================================================
# 분산 락 (Stampede Prevention)
# ============================================================

def acquire_token_refresh_lock(db: Optional[Session] = None) -> Tuple[bool, Session]:
    """
    토큰 갱신 분산 락 획득.
    
    Returns:
        (성공 여부, 세션) - 세션은 호출자가 release 시 사용
    """
    owned_session = db is None
    session = db or SessionLocal()
    
    try:
        setting = _get_setting(session)
        now = datetime.now()
        
        if setting.token_refresh_locked_at:
            lock_age = now - setting.token_refresh_locked_at
            if lock_age < timedelta(seconds=LOCK_TIMEOUT_SEC):
                logger.debug("[KIS Lock] 다른 프로세스가 갱신 중 (locked_at=%s)", setting.token_refresh_locked_at)
                if owned_session:
                    session.close()
                return False, session
            else:
                logger.warning("[KIS Lock] 락 타임아웃됨, 강제 해제 후 재획득 (locked_at=%s)", setting.token_refresh_locked_at)
        
        setting.token_refresh_locked_at = now
        session.commit()
        logger.info("[KIS Lock] 락 획득 성공")
        return True, session
    except Exception as exc:
        logger.error("[KIS Lock] 락 획득 실패: %s", exc)
        if owned_session:
            session.close()
        return False, session


def release_token_refresh_lock(db: Session) -> None:
    """토큰 갱신 분산 락 해제"""
    try:
        setting = _get_setting(db)
        setting.token_refresh_locked_at = None
        db.commit()
        logger.info("[KIS Lock] 락 해제 완료")
    except Exception as exc:
        logger.error("[KIS Lock] 락 해제 실패: %s", exc)


# ============================================================
# 서킷브레이커 (Circuit Breaker)
# ============================================================

@dataclass
class CircuitState:
    """서킷브레이커 상태 조회 결과"""
    failure_count: int
    circuit_open: bool
    circuit_open_until: Optional[datetime]
    can_attempt: bool
    backoff_seconds: float


def get_circuit_state(db: Optional[Session] = None) -> CircuitState:
    """현재 서킷브레이커 상태 조회"""
    owned_session = db is None
    session = db or SessionLocal()
    
    try:
        setting = _get_setting(session)
        now = datetime.now()
        
        failure_count = setting.kis_auth_failure_count or 0
        circuit_open_until = setting.kis_circuit_open_until
        
        # 서킷 오픈 여부 판단
        circuit_open = False
        can_attempt = True
        
        if circuit_open_until and circuit_open_until > now:
            circuit_open = True
            can_attempt = False
            logger.debug("[KIS Circuit] 서킷 오픈 상태 (until=%s)", circuit_open_until)
        elif failure_count >= FAILURE_THRESHOLD:
            # 서킷 오픈 조건 충족했으나 타임아웃 미설정 → 하프오픈 허용
            can_attempt = True
            logger.debug("[KIS Circuit] 하프오픈 상태 (failure_count=%d)", failure_count)
        
        # 백오프 계산
        backoff_seconds = min(2 ** failure_count, MAX_BACKOFF_SEC) if failure_count > 0 else 0
        
        return CircuitState(
            failure_count=failure_count,
            circuit_open=circuit_open,
            circuit_open_until=circuit_open_until,
            can_attempt=can_attempt,
            backoff_seconds=backoff_seconds,
        )
    finally:
        if owned_session:
            session.close()


def record_auth_failure(db: Optional[Session] = None) -> CircuitState:
    """인증 실패 기록 및 서킷브레이커 상태 업데이트"""
    owned_session = db is None
    session = db or SessionLocal()
    
    try:
        setting = _get_setting(session)
        setting.kis_auth_failure_count = (setting.kis_auth_failure_count or 0) + 1
        
        if setting.kis_auth_failure_count >= FAILURE_THRESHOLD:
            # 서킷 오픈
            setting.kis_circuit_open_until = datetime.now() + timedelta(seconds=CIRCUIT_OPEN_DURATION_SEC)
            logger.warning(
                "[KIS Circuit] 🔴 서킷 오픈! (failure_count=%d, open_until=%s)",
                setting.kis_auth_failure_count,
                setting.kis_circuit_open_until,
            )
        
        session.commit()
        
        return CircuitState(
            failure_count=setting.kis_auth_failure_count,
            circuit_open=setting.kis_circuit_open_until is not None,
            circuit_open_until=setting.kis_circuit_open_until,
            can_attempt=False,
            backoff_seconds=min(2 ** setting.kis_auth_failure_count, MAX_BACKOFF_SEC),
        )
    finally:
        if owned_session:
            session.close()


def record_auth_success(db: Optional[Session] = None) -> None:
    """인증 성공 기록 및 서킷브레이커 리셋"""
    owned_session = db is None
    session = db or SessionLocal()
    
    try:
        setting = _get_setting(session)
        
        if setting.kis_auth_failure_count > 0 or setting.kis_circuit_open_until:
            logger.info(
                "[KIS Circuit] 🟢 서킷 리셋 (이전 failure_count=%d)",
                setting.kis_auth_failure_count or 0,
            )
        
        setting.kis_auth_failure_count = 0
        setting.kis_circuit_open_until = None
        session.commit()
    finally:
        if owned_session:
            session.close()


# ============================================================
# 토큰 만료 체크 (Refresh Window 로직)
# ============================================================

@dataclass
class TokenStatus:
    """토큰 상태 조회 결과"""
    token: Optional[str]
    needs_refresh: bool
    is_expired: bool
    expires_at: Optional[datetime]
    time_until_expiry: Optional[timedelta]


def check_token_status(
    token: Optional[str],
    expires_at: Optional[datetime],
) -> TokenStatus:
    """
    토큰 상태 판단.
    
    - needs_refresh: 갱신 필요 (만료 2시간 전)
    - is_expired: 완전 만료 (만료 30분 전)
    """
    if not token or not expires_at:
        return TokenStatus(
            token=None,
            needs_refresh=True,
            is_expired=True,
            expires_at=None,
            time_until_expiry=None,
        )
    
    now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
    time_until_expiry = expires_at - now
    
    # 완전 만료 (30분 미만)
    if time_until_expiry <= timedelta(hours=HARD_EXPIRY_BUFFER_HOURS):
        return TokenStatus(
            token=None,
            needs_refresh=True,
            is_expired=True,
            expires_at=expires_at,
            time_until_expiry=time_until_expiry,
        )
    
    # 갱신 필요 (2시간 미만)
    if time_until_expiry <= timedelta(hours=REFRESH_WINDOW_HOURS):
        return TokenStatus(
            token=token,
            needs_refresh=True,
            is_expired=False,
            expires_at=expires_at,
            time_until_expiry=time_until_expiry,
        )
    
    # 정상
    return TokenStatus(
        token=token,
        needs_refresh=False,
        is_expired=False,
        expires_at=expires_at,
        time_until_expiry=time_until_expiry,
    )
