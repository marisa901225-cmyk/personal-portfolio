"""파서 유틸리티 함수들"""
from __future__ import annotations

import hashlib
from datetime import datetime


def generate_hash(date: datetime, merchant: str, amount: float, method: str) -> str:
    """거래 고유 해시 생성 (중복 체크용)"""
    key = f"{date.isoformat()}|{merchant}|{amount}|{method}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()


def build_dedup_key(date: datetime, merchant: str, amount: float, method: str) -> str:
    """DB에 이미 있는 거래 중복 체크용 키"""
    if isinstance(date, datetime):
        date_key = date.date().isoformat()
    else:
        date_key = date.isoformat()
    return f"{date_key}|{merchant}|{amount}|{method}"


def build_core_key(date: datetime, merchant: str, method: str) -> str:
    """금액을 제외한 중복 체크용 키 (일자/가맹점/결제수단)"""
    if isinstance(date, datetime):
        date_key = date.date().isoformat()
    else:
        date_key = date.isoformat()
    return f"{date_key}|{merchant}|{method}"


def build_methodless_key(date: datetime, merchant: str, amount: float) -> str:
    """결제수단을 제외한 중복 체크용 키 (일자/가맹점/금액)"""
    if isinstance(date, datetime):
        date_key = date.date().isoformat()
    else:
        date_key = date.isoformat()
    return f"{date_key}|{merchant}|{amount}"


def build_abs_dedup_key(date: datetime, merchant: str, amount: float, method: str) -> str:
    """카드 사용 내역 등 부호 차이를 보정한 중복 체크용 키"""
    return build_dedup_key(date, merchant, abs(amount), method)


GENERIC_METHODS = {"creditcard", "checkcard", "banktransfer"}


def is_generic_method(method: str) -> bool:
    return method.strip().lower() in GENERIC_METHODS
