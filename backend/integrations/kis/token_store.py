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


def _load_token_key() -> bytes:
    raw = os.getenv("KIS_TOKEN_KEY")
    if not raw:
        raise RuntimeError("KIS_TOKEN_KEY is not set")
    try:
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


def read_kis_token(db: Optional[Session] = None) -> Optional[str]:
    """
    DB에서 KIS 토큰을 읽어온다. (재시도 로직 포함)
    
    - 토큰이 없거나 복호화 실패 시 None 반환
    - 만료 시간이 설정되어 있고, 현재 시간 + 1시간 > 만료 시간이면 None 반환 (재발급 필요)
    - DB 락 등으로 조회 실패 시 최대 10번 재시도 (현실적 타협).
    """
    import time
    from sqlalchemy.exc import OperationalError

    max_retries = 10
    retry_delay = 0.2  # seconds (짧게 여러 번 시도)

    for attempt in range(max_retries):
        owned_session = db is None
        session = db or SessionLocal()
        
        try:
            setting = _get_or_create_setting(session)
            if not setting.kis_token_encrypted:
                logger.info("[KIS Token] 저장된 토큰 없음")
                return None
            
            # 만료 시간 검사
            if setting.kis_token_expires_at:
                expires_at = setting.kis_token_expires_at
                now = (
                    datetime.now(expires_at.tzinfo)
                    if expires_at.tzinfo is not None
                    else datetime.now()
                )
                from datetime import timedelta
                if expires_at <= now + timedelta(hours=1):
                    logger.info("[KIS Token] 토큰 만료됨 (expires_at=%s, now=%s)", expires_at, now)
                    return None
                logger.debug("[KIS Token] 토큰 유효 (만료까지 %s 남음)", expires_at - now)
            else:
                logger.debug("[KIS Token] 만료 시간 미설정, 기존 토큰 사용")
            
            return _decrypt_token(setting.kis_token_encrypted)

        except OperationalError as exc:
            if "locked" in str(exc).lower():
                logger.warning("[KIS Token] DB Locked! Retrying (%d/%d)...", attempt + 1, max_retries)
                time.sleep(retry_delay)
                continue
            logger.error("[KIS Token] DB OperationalError: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Failed to read KIS token from DB: %s", exc)
            return None
        finally:
            if owned_session:
                session.close()
    
    logger.error("[KIS Token] Failed to read token after %d retries.", max_retries)
    return None


def save_kis_token(
    token: str,
    expires_at: Optional[datetime],
    db: Optional[Session] = None,
) -> None:
    owned_session = db is None
    if owned_session:
        db = SessionLocal()
    try:
        setting = _get_or_create_setting(db)
        setting.kis_token_encrypted = _encrypt_token(token)
        setting.kis_token_expires_at = expires_at
        db.commit()
        logger.info("[KIS Token] 토큰 저장 완료 - 만료시간: %s", expires_at)
    except Exception as exc:
        logger.warning("Failed to save KIS token to DB: %s", exc)
    finally:
        if owned_session and db is not None:
            db.close()

