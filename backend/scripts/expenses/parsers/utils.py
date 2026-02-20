"""파서 유틸리티 함수들"""
from __future__ import annotations
from typing import Any

import hashlib
from datetime import datetime


def _to_date_str(date: Any, date_only: bool = False) -> str:
    import pandas as pd
    if isinstance(date, float) or pd.isna(date):
        return "InvalidDate"
    if isinstance(date, datetime):
        return date.date().isoformat() if date_only else date.isoformat()
    try:
        return str(date.isoformat())
    except:
        return str(date)


def generate_hash(date: datetime, merchant: str, amount: float, method: str) -> str:
    """거래 고유 해시 생성 (중복 체크용)"""
    date_str = _to_date_str(date)
    key = f"{date_str}|{merchant}|{amount}|{method}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()


def build_dedup_key(date: datetime, merchant: str, amount: float, method: str) -> str:
    """DB에 이미 있는 거래 중복 체크용 키"""
    date_key = _to_date_str(date, date_only=True)
    return f"{date_key}|{merchant}|{amount}|{method}"


def build_core_key(date: datetime, merchant: str, method: str) -> str:
    """금액을 제외한 중복 체크용 키 (일자/가맹점/결제수단)"""
    date_key = _to_date_str(date, date_only=True)
    return f"{date_key}|{merchant}|{method}"


def build_methodless_key(date: datetime, merchant: str, amount: float) -> str:
    """결제수단을 제외한 중복 체크용 키 (일자/가맹점/금액)"""
    date_key = _to_date_str(date, date_only=True)
    return f"{date_key}|{merchant}|{amount}"


def build_abs_dedup_key(date: datetime, merchant: str, amount: float, method: str) -> str:
    """카드 사용 내역 등 부호 차이를 보정한 중복 체크용 키"""
    return build_dedup_key(date, merchant, abs(amount), method)


GENERIC_METHODS = {"creditcard", "checkcard", "banktransfer"}


def is_generic_method(method: str) -> bool:
    return method.strip().lower() in GENERIC_METHODS
