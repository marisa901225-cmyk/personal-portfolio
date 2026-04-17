from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from typing import Optional

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from sqlalchemy.orm import Session

from ...core.db import SessionLocal
from ...core.models import Setting
from ...services.users import get_or_create_single_user

logger = logging.getLogger(__name__)

_TOKEN_NONCE_SIZE = 12
_TOKEN_TAG_SIZE = 16


def _slot_columns(slot: int) -> tuple[str, str]:
    if int(slot) == 1:
        return "kis_token_encrypted1", "kis_token_expires_at1"
    return "kis_token_encrypted", "kis_token_expires_at"


def _load_token_key() -> bytes:
    from ...core.config import settings
    raw = settings.kis_token_key
    if not raw:
        raise RuntimeError("KIS_TOKEN_KEY is not set in environment or .env")
    try:
        # Add padding if missing
        padding = len(raw) % 4
        if padding > 0:
            raw += "=" * (4 - padding)
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise RuntimeError("KIS_TOKEN_KEY must be base64-encoded") from exc
    if len(key) != 32:
        raise RuntimeError("KIS_TOKEN_KEY must decode to 32 bytes")
    return key


def _encrypt_token(token: str) -> str:
    key = _load_token_key()
    nonce = get_random_bytes(_TOKEN_NONCE_SIZE)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(token.encode("utf-8"))
    payload = nonce + tag + ciphertext
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decrypt_token(payload: str) -> str:
    key = _load_token_key()
    data = base64.urlsafe_b64decode(payload)
    if len(data) < _TOKEN_NONCE_SIZE + _TOKEN_TAG_SIZE:
        raise RuntimeError("Invalid encrypted token payload")
    nonce = data[:_TOKEN_NONCE_SIZE]
    tag = data[_TOKEN_NONCE_SIZE : _TOKEN_NONCE_SIZE + _TOKEN_TAG_SIZE]
    ciphertext = data[_TOKEN_NONCE_SIZE + _TOKEN_TAG_SIZE :]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")


def _get_or_create_setting(db: Session) -> Setting:
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


import asyncio
import threading

# 비동기 갱신 작업 추적 (Stampede 방지용)
_background_refresh_lock = threading.Lock()
_refresh_in_progress = False


def trigger_async_refresh() -> None:
    """
    백그라운드에서 KIS 토큰 갱신을 트리거한다.
    이미 진행 중인 경우 중복 실행하지 않는다.
    """
    global _refresh_in_progress
    
    with _background_refresh_lock:
        if _refresh_in_progress:
            logger.debug("[KIS Token] 이미 백그라운드 갱신 진행 중")
            return
        _refresh_in_progress = True

    def _do_refresh():
        global _refresh_in_progress
        try:
            logger.info("[KIS Token] 🔄 백그라운드 토큰 갱신 시작...")
            # KIS 인증 모듈 임포트 (Circular Import 방지)
            from .open_trading.kis_auth_rest import auth
            # 강제 재발급(force=True) 수행
            auth(force=True)
            logger.info("[KIS Token] ✅ 백그라운드 토큰 갱신 완료")
        except Exception as exc:
            logger.exception("[KIS Token] ❌ 백그라운드 토큰 갱신 실패: %s", exc)
        finally:
            with _background_refresh_lock:
                _refresh_in_progress = False

    # asyncio 루프가 있는 경우와 없는 경우 모두 대응
    try:
        loop = asyncio.get_running_loop()
        # await을 하지 않고 백그라운드 태스크로 실행
        loop.run_in_executor(None, _do_refresh)
        logger.debug("[KIS Token] Asyncio executor를 통한 갱신 트리거")
    except RuntimeError:
        # 루프가 없는 경우 별도 스레드로 실행
        thread = threading.Thread(target=_do_refresh, daemon=True)
        thread.start()
        logger.debug("[KIS Token] 스레드를 통한 갱신 트리거")


def read_kis_token_record(
    slot: int = 0,
    db: Optional[Session] = None,
) -> tuple[Optional[str], Optional[datetime]]:
    """
    DB에서 KIS 토큰을 읽어온다. (재시도 로직 포함)
    
    - 토큰이 없거나 복호화 실패 시 None 반환
    - Refresh Window: 만료 2시간 전부터 갱신 필요 플래그 세팅
    - Hard Expiry: 만료 30분 전부터 None 반환 (재발급 필수)
    - DB 락 등으로 조회 실패 시 최대 10번 재시도
    """
    import time
    from datetime import timedelta
    from sqlalchemy.exc import OperationalError
    
    # 리프레시 윈도우 설정
    REFRESH_WINDOW_HOURS = 2
    HARD_EXPIRY_BUFFER_HOURS = 0.5

    max_retries = 10
    retry_delay = 0.2  # seconds (짧게 여러 번 시도)
    token_field, expires_field = _slot_columns(slot)

    for attempt in range(max_retries):
        owned_session = db is None
        session = db or SessionLocal()
        
        try:
            setting = _get_or_create_setting(session)
            token_payload = getattr(setting, token_field, None)
            expires_at = getattr(setting, expires_field, None)
            if not token_payload:
                logger.info("[KIS Token][slot=%s] 저장된 토큰 없음", slot)
                return None, None
            
            # 만료 시간 검사
            if expires_at:
                now = (
                    datetime.now(expires_at.tzinfo)
                    if expires_at.tzinfo is not None
                    else datetime.now()
                )
                time_until_expiry = expires_at - now
                
                # 완전 만료 (30분 미만) - 반드시 재발급 필요
                if time_until_expiry <= timedelta(hours=HARD_EXPIRY_BUFFER_HOURS):
                    logger.warning(
                        "[KIS Token][slot=%s] ⚠️ 토큰 만료 임박! (expires_at=%s, 남은시간=%s)",
                        slot, expires_at, time_until_expiry
                    )
                    return None, expires_at
                
                # 갱신 필요 (2시간 미만) - 토큰은 반환하되 백그라운드 갱신 트리거
                if slot == 0 and time_until_expiry <= timedelta(hours=REFRESH_WINDOW_HOURS):
                    logger.info(
                        "[KIS Token][slot=%s] 🔄 갱신 윈도우 진입 (expires_at=%s, 남은시간=%s). 백그라운드 갱신을 시도합니다.",
                        slot, expires_at, time_until_expiry
                    )
                    trigger_async_refresh()
                
                logger.debug("[KIS Token][slot=%s] 토큰 유효 (만료까지 %s 남음)", slot, time_until_expiry)
            else:
                logger.debug("[KIS Token][slot=%s] 만료 시간 미설정, 기존 토큰 사용", slot)
            
            return _decrypt_token(token_payload), expires_at

        except OperationalError as exc:
            if "locked" in str(exc).lower():
                logger.warning("[KIS Token][slot=%s] DB Locked! Retrying (%d/%d)...", slot, attempt + 1, max_retries)
                time.sleep(retry_delay)
                continue
            logger.error("[KIS Token][slot=%s] DB OperationalError: %s", slot, exc)
            return None, None
        except Exception as exc:
            logger.warning("Failed to read KIS token from DB (slot=%s): %s", slot, exc)
            return None, None
        finally:
            if owned_session:
                session.close()
    
    logger.error("[KIS Token][slot=%s] Failed to read token after %d retries.", slot, max_retries)
    return None, None


def read_kis_token(slot: int = 0, db: Optional[Session] = None) -> Optional[str]:
    token, _ = read_kis_token_record(slot=slot, db=db)
    return token


def save_kis_token(
    token: str,
    expires_at: Optional[datetime],
    slot: int = 0,
    db: Optional[Session] = None,
) -> None:
    owned_session = db is None
    if owned_session:
        db = SessionLocal()
    try:
        setting = _get_or_create_setting(db)
        token_field, expires_field = _slot_columns(slot)
        setattr(setting, token_field, _encrypt_token(token))
        setattr(setting, expires_field, expires_at)
        db.commit()
        logger.info("[KIS Token][slot=%s] 토큰 저장 완료 - 만료시간: %s", slot, expires_at)
    except Exception as exc:
        logger.warning("Failed to save KIS token to DB (slot=%s): %s", slot, exc)
    finally:
        if owned_session and db is not None:
            db.close()
