from __future__ import annotations

import base64
import logging

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

logger = logging.getLogger(__name__)

KIS_SECRET_FIELDS = {
    "kis_app",
    "kis_sec",
    "kis_acct_stock",
    "kis_prod",
    "kis_htsid",
    "kis_agent",
}

_SECRET_PREFIX = "enc:"
_NONCE_SIZE = 12
_TAG_SIZE = 16


def _load_token_key() -> bytes:
    from ..core.config import settings
    raw = settings.kis_token_key
    if not raw:
        raise RuntimeError("KIS_TOKEN_KEY is not set in environment or .env")
    try:
        padding = len(raw) % 4
        if padding > 0:
            raw += "=" * (4 - padding)
        key = base64.urlsafe_b64decode(raw)
    except Exception as exc:
        raise RuntimeError("KIS_TOKEN_KEY must be base64-encoded") from exc
    if len(key) != 32:
        raise RuntimeError("KIS_TOKEN_KEY must decode to 32 bytes")
    return key

def has_kis_token_key() -> bool:
    from ..core.config import settings
    return bool(settings.kis_token_key)


def is_kis_secret_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(_SECRET_PREFIX)


def encrypt_kis_secret(value: str | None) -> str | None:
    if value is None:
        return None
    value_str = str(value).strip()
    if not value_str:
        return None
    if is_kis_secret_encrypted(value_str):
        return value_str
    key = _load_token_key()
    nonce = get_random_bytes(_NONCE_SIZE)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(value_str.encode("utf-8"))
    payload = nonce + tag + ciphertext
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{_SECRET_PREFIX}{encoded}"


def decrypt_kis_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not is_kis_secret_encrypted(value):
        if not has_kis_token_key():
            raise RuntimeError("KIS_TOKEN_KEY is required to access stored secrets")
        return value
    key = _load_token_key()
    payload_b64 = value[len(_SECRET_PREFIX):]
    try:
        padding = len(payload_b64) % 4
        if padding > 0:
            payload_b64 += "=" * (4 - padding)
        data = base64.urlsafe_b64decode(payload_b64)
    except Exception as exc:
        raise RuntimeError("Invalid encrypted KIS secret payload") from exc
    if len(data) < _NONCE_SIZE + _TAG_SIZE:
        raise RuntimeError("Invalid encrypted KIS secret payload")
    nonce = data[:_NONCE_SIZE]
    tag = data[_NONCE_SIZE : _NONCE_SIZE + _TAG_SIZE]
    ciphertext = data[_NONCE_SIZE + _TAG_SIZE :]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
