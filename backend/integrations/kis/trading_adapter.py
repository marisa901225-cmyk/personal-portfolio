"""
KIS 한국투자증권 Trading Adapter
================================
TradingAPI 프로토콜을 KIS OpenAPI로 구현하는 어댑터.

환경변수:
    TRADING_ENGINE_API_FACTORY=backend.integrations.kis.trading_adapter:create_trading_api

API 참고:
    - 주식주문(현금) [v1_국내주식-001]: POST /uapi/domestic-stock/v1/trading/order-cash
    - 주식잔고조회   [v1_국내주식-006]: GET  /uapi/domestic-stock/v1/trading/inquire-balance
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests
from backend.integrations.kis.rest_rate_limiter import throttle_rest_min_gap
from backend.integrations.kis.secondary_market_context import build_secondary_market_context
from backend.integrations.kis.token_store import (
    kis_token_issue_lock,
    log_kis_token_issue_failure,
    read_kis_token_record,
    save_kis_token,
)

from .daily_bars_disk_cache import DEFAULT_DAILY_BARS_DISK_CACHE_PATH, DailyBarsDiskCache
from .trading_account_mixin import KISAccountTradingMixin
from .trading_market_data_mixin import KISMarketDataMixin

logger = logging.getLogger(__name__)

_KIS_HTTP_CONNECT_TIMEOUT_SEC = 3.05
_KIS_HTTP_READ_TIMEOUT_SEC = 10.0
_KIS_HTTP_GET_MAX_ATTEMPTS = 3
_KIS_HTTP_RETRY_BACKOFF_SEC = 0.35
_KIS_HTTP_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


_KIS_HTTP_PATH_MIN_GAP_SEC = {
    "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice": _env_float(
        "KIS_DAILY_CHART_MIN_GAP_SEC",
        0.12,
    ),
    "/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice": _env_float(
        "KIS_DAILY_INDEX_CHART_MIN_GAP_SEC",
        0.12,
    ),
    "/uapi/domestic-stock/v1/quotations/inquire-price": _env_float(
        "KIS_QUOTE_MIN_GAP_SEC",
        0.10,
    ),
}
_KIS_DAILY_BARS_CACHE_TTL_SEC = max(0.0, _env_float("KIS_DAILY_BARS_CACHE_TTL_SEC", 300.0))
_KIS_DAILY_INDEX_BARS_CACHE_TTL_SEC = max(0.0, _env_float("KIS_DAILY_INDEX_BARS_CACHE_TTL_SEC", 300.0))
_KIS_QUOTE_CACHE_TTL_SEC = max(0.0, _env_float("KIS_QUOTE_CACHE_TTL_SEC", 20.0))
_KIS_RANK_MARKET_DIV_CODES: tuple[str, ...] = ("J", "NX")
_KIS_VALUE_RANK_PRICE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("0", "1000"),
    ("1000", "2000"),
    ("2000", "5000"),
    ("5000", "10000"),
    ("10000", "20000"),
    ("20000", "50000"),
    ("50000", "100000"),
    ("100000", "200000"),
    ("200000", "500000"),
    ("500000", "9999999"),
)
_AUTH_EXPIRY_BUFFER_SEC = 60
_SLOT2_EXPECTED_CALLERS: tuple[str, ...] = (
    "backend.scripts.run_pension_rebalance_scheduler",
    "backend.scripts.rebalance_kis_pension_account",
    "backend.scripts.check_kis_pension_account",
)


def _slot2_unexpected_context() -> str | None:
    cmdline = " ".join(sys.argv)
    for expected in _SLOT2_EXPECTED_CALLERS:
        if expected in cmdline:
            return None
    return cmdline


@dataclass(slots=True, frozen=True)
class KISDirectCredentials:
    app_key: str
    app_secret: str
    account: str
    product: str = "01"
    base_url: str = "https://openapi.koreainvestment.com:9443"
    user_agent: str = "MyAsset"
    token_slot: int | None = None


class KISTradingBase:
    """KIS OpenAPI 공통 세션/헬퍼 구현체."""

    _rank_market_div_codes = _KIS_RANK_MARKET_DIV_CODES
    _value_rank_price_buckets = _KIS_VALUE_RANK_PRICE_BUCKETS
    _daily_bars_cache_ttl_sec = _KIS_DAILY_BARS_CACHE_TTL_SEC
    _daily_index_bars_cache_ttl_sec = _KIS_DAILY_INDEX_BARS_CACHE_TTL_SEC
    _quote_cache_ttl_sec = _KIS_QUOTE_CACHE_TTL_SEC

    def __init__(self, credentials: KISDirectCredentials | None = None) -> None:
        from . import kis_client as core

        self._direct_credentials = credentials
        self._direct_access_token: str | None = None
        self._direct_token_expires_at: datetime | None = None
        self._session = requests.Session()
        self._daily_bars_cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}
        self._daily_index_bars_cache: dict[tuple[str, str, int], tuple[float, pd.DataFrame]] = {}
        self._quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._holiday_rows_cache: dict[str, tuple[str, list[dict[str, Any]]]] = {}
        self._daily_bars_disk_cache = DailyBarsDiskCache(DEFAULT_DAILY_BARS_DISK_CACHE_PATH)
        self._secondary_market_ctx = None
        self._core = core
        self._ka = None
        self._rest_throttle = None

        if credentials is None:
            core._ensure_kis_modules_loaded()
            core._ensure_auth()
            self._ka = core.ka
            import kis_auth_rest  # type: ignore

            self._rest_throttle = kis_auth_rest._throttle_rest
            self._secondary_market_ctx = build_secondary_market_context(
                min_gap_by_path=_KIS_HTTP_PATH_MIN_GAP_SEC,
            )
        if self._secondary_market_ctx is not None:
            logger.info("[KIS TradingAPI] 보조 조회 전용 appkey 활성화")
        logger.info("[KIS TradingAPI] 어댑터 초기화 완료")

    def _headers(self, tr_id: str, tr_cont: str = "") -> dict[str, str]:
        direct_credentials = getattr(self, "_direct_credentials", None)
        if direct_credentials is not None:
            token = self._ensure_direct_auth()
            h = {
                "content-type": "application/json",
                "authorization": f"Bearer {token}",
                "appkey": direct_credentials.app_key,
                "appsecret": direct_credentials.app_secret,
                "tr_id": tr_id,
                "custtype": "P",
                "User-Agent": direct_credentials.user_agent,
            }
            if tr_cont:
                h["tr_cont"] = tr_cont
            return h

        if self._ka is None:
            raise RuntimeError("KIS adapter is not initialized")
        h = self._ka._getBaseHeader()
        h["tr_id"] = tr_id
        h["custtype"] = "P"
        if tr_cont:
            h["tr_cont"] = tr_cont
        return h

    def _base_url(self) -> str:
        direct_credentials = getattr(self, "_direct_credentials", None)
        if direct_credentials is not None:
            return direct_credentials.base_url
        if self._ka is None:
            raise RuntimeError("KIS adapter is not initialized")
        return self._ka.getTREnv().my_url

    def _account(self) -> tuple[str, str]:
        direct_credentials = getattr(self, "_direct_credentials", None)
        if direct_credentials is not None:
            acct = direct_credentials.account
            return acct[:8], acct[8:10] if len(acct) >= 10 else (direct_credentials.product or "01")
        if self._ka is None:
            raise RuntimeError("KIS adapter is not initialized")
        acct = self._ka.getTREnv().my_acct
        return acct[:8], acct[8:10] if len(acct) >= 10 else "01"

    def _direct_token_is_valid(self) -> bool:
        if not self._direct_access_token:
            return False
        if self._direct_token_expires_at is None:
            return True
        return datetime.now() + timedelta(seconds=_AUTH_EXPIRY_BUFFER_SEC) < self._direct_token_expires_at

    def _reuse_direct_token_from_db(self, *, force: bool = False) -> str | None:
        credentials = getattr(self, "_direct_credentials", None)
        if credentials is None or credentials.token_slot is None:
            return None

        previous_token = self._direct_access_token
        cached_token, cached_expires_at = read_kis_token_record(slot=credentials.token_slot)
        if not cached_token:
            return None

        self._direct_access_token = cached_token
        self._direct_token_expires_at = cached_expires_at
        if self._direct_token_is_valid() and (not force or cached_token != previous_token):
            logger.debug(
                "[KIS TradingAPI] direct token reused from DB slot=%s expires_at=%s",
                credentials.token_slot,
                cached_expires_at,
            )
            return cached_token
        return None

    def _ensure_direct_auth(self, *, force: bool = False) -> str:
        credentials = getattr(self, "_direct_credentials", None)
        if credentials is None:
            raise RuntimeError("direct KIS credentials are not configured")
        if not force and self._direct_token_is_valid():
            return str(self._direct_access_token)

        if not force:
            cached_token = self._reuse_direct_token_from_db(force=False)
            if cached_token:
                return cached_token

        issue_lock = kis_token_issue_lock() if credentials.token_slot is not None else nullcontext()
        with issue_lock:
            cached_token = self._reuse_direct_token_from_db(force=force)
            if cached_token:
                return cached_token

            payload = {
                "grant_type": "client_credentials",
                "appkey": credentials.app_key,
                "appsecret": credentials.app_secret,
            }
            self._throttle_rest()
            response = self._session.post(
                f"{credentials.base_url}/oauth2/tokenP",
                headers={"content-type": "application/json"},
                data=json.dumps(payload),
                timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
            )
        try:
            data = response.json()
        except ValueError:
            data = {}
        token = str(data.get("access_token") or "").strip()
        if response.status_code >= 400 or not token:
            error_code = data.get("msg_cd") or data.get("error_code")
            error_message = data.get("msg1") or data.get("error_description")
            if not error_message:
                error_message = (response.text or "").strip()[:300]
            if credentials.token_slot is not None:
                log_kis_token_issue_failure(
                    slot=int(credentials.token_slot),
                    status_code=int(response.status_code),
                    error_code=str(error_code or "") or None,
                    error_message=str(error_message or "") or None,
                )
            raise RuntimeError(
                f"KIS direct auth failed: {response.status_code} {error_code} {error_message}"
            )
        self._direct_access_token = token
        expires_raw = str(data.get("access_token_token_expired") or "").strip()
        if expires_raw:
            try:
                self._direct_token_expires_at = datetime.strptime(expires_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                self._direct_token_expires_at = None
        if credentials.token_slot is not None:
            save_kis_token(token, self._direct_token_expires_at, slot=credentials.token_slot)
            logger.info(
                "[KIS Token][slot=%s] direct auth refreshed (expires_at=%s)",
                credentials.token_slot,
                self._direct_token_expires_at.isoformat(sep=" ", timespec="seconds")
                if self._direct_token_expires_at
                else "unknown",
            )
            if int(credentials.token_slot) == 2:
                unexpected_cmdline = _slot2_unexpected_context()
                if unexpected_cmdline:
                    logger.warning(
                        "[KIS Token][slot=2] 예상 외 발급 감지 cmd=%s expires_at=%s",
                        unexpected_cmdline,
                        self._direct_token_expires_at,
                    )
        return token

    def _throttle_rest(self) -> None:
        throttle = getattr(self, "_rest_throttle", None)
        if callable(throttle):
            throttle()
            return
        time.sleep(0.05)

    def _throttle_path_min_gap(self, path: str) -> None:
        min_gap_sec = _KIS_HTTP_PATH_MIN_GAP_SEC.get(str(path or "").strip())
        if not min_gap_sec:
            return
        throttle_rest_min_gap(
            scope=f"kis_get:{path}",
            min_gap_sec=min_gap_sec,
        )

    def _market_get(self, path: str, tr_id: str, params: dict, tr_cont: str = "") -> dict:
        secondary_market_ctx = getattr(self, "_secondary_market_ctx", None)
        if secondary_market_ctx is None:
            return self._get(path, tr_id, params, tr_cont)

        try:
            return secondary_market_ctx.get(path, tr_id, params, tr_cont)
        except Exception as exc:
            logger.warning(
                "[KIS TradingAPI] 보조 조회 전용 appkey 실패 -> 기본 appkey fallback path=%s tr_id=%s error=%s",
                path,
                tr_id,
                exc,
            )
            return self._get(path, tr_id, params, tr_cont)

    @staticmethod
    def _copy_cached_value(value: Any) -> Any:
        if isinstance(value, pd.DataFrame):
            return value.copy(deep=True)
        if isinstance(value, dict):
            return dict(value)
        return value

    def _cache_lookup(self, cache_name: str, key: Any, ttl_sec: float) -> Any | None:
        if ttl_sec <= 0:
            return None
        cache = getattr(self, cache_name, None)
        if not isinstance(cache, dict):
            cache = {}
            setattr(self, cache_name, cache)
        entry = cache.get(key)
        if not entry:
            return None
        stored_at, payload = entry
        if (time.monotonic() - float(stored_at)) > ttl_sec:
            cache.pop(key, None)
            return None
        return self._copy_cached_value(payload)

    def _cache_store(self, cache_name: str, key: Any, value: Any, ttl_sec: float) -> Any:
        copied = self._copy_cached_value(value)
        if ttl_sec > 0:
            cache = getattr(self, cache_name, None)
            if not isinstance(cache, dict):
                cache = {}
                setattr(self, cache_name, cache)
            cache[key] = (time.monotonic(), copied)
        return self._copy_cached_value(copied)

    def _is_expired_token_response(self, response: requests.Response, data: dict | None = None) -> bool:
        if getattr(self, "_direct_credentials", None) is not None:
            payload = data if isinstance(data, dict) else {}
            msg_cd = str(payload.get("msg_cd") or "").strip()
            msg1 = str(payload.get("msg1") or "").strip().lower()
            text = str(getattr(response, "text", "") or "").lower()
            return (
                msg_cd == "EGW00123"
                or "token expired" in msg1
                or "기간이 만료된 token" in msg1
                or (response.status_code == 401 and "token" in text)
            )
        checker = getattr(getattr(self, "_ka", None), "is_expired_token_response", None)
        if callable(checker):
            return bool(checker(response, data=data))
        return False

    def _force_reauth_current_env(self) -> None:
        if getattr(self, "_direct_credentials", None) is not None:
            self._ensure_direct_auth(force=True)
            return
        refresher = getattr(getattr(self, "_ka", None), "force_reauth_current_env", None)
        if callable(refresher):
            refresher()

    @staticmethod
    def _normalize_yyyymmdd(value: str) -> str:
        raw = str(value or "").strip()
        if "-" in raw:
            raw = raw.replace("-", "")
        return raw[:8]

    @staticmethod
    def _to_int(value: Any) -> int:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0
        try:
            return int(float(text))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _to_float(value: Any) -> float:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _is_retryable_get_exception(exc: requests.exceptions.RequestException) -> bool:
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            return True

        if isinstance(exc, requests.exceptions.HTTPError):
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            return status_code in _KIS_HTTP_RETRYABLE_STATUS

        return False

    @staticmethod
    def _get_retry_delay_seconds(attempt: int) -> float:
        return _KIS_HTTP_RETRY_BACKOFF_SEC * (2 ** max(0, attempt - 1))

    @staticmethod
    def _order_division_code(order_type: str) -> str:
        order_kind = str(order_type or "").strip().lower()
        ord_dvsn_map = {
            "limit": "00",
            "market": "01",
            "mkt": "01",
            "conditional": "02",
            "best": "03",
            "priority": "04",
        }
        return ord_dvsn_map.get(order_kind, "00")

    def _get(self, path: str, tr_id: str, params: dict, tr_cont: str = "") -> dict:
        url = f"{self._base_url()}{path}"
        force_refreshed = False
        for attempt in range(1, _KIS_HTTP_GET_MAX_ATTEMPTS + 1):
            if getattr(self, "_direct_credentials", None) is None:
                self._core._ensure_auth()
            headers = self._headers(tr_id, tr_cont)
            self._throttle_rest()
            self._throttle_path_min_gap(path)
            try:
                res = self._session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
                )
                data = res.json() if "json" in dir(res) else None
                if self._is_expired_token_response(res, data=data):
                    if force_refreshed:
                        res.raise_for_status()
                    logger.warning(
                        "[KIS API] GET 응답에서 만료 토큰 감지; 강제 재인증 후 재시도 tr_id=%s path=%s",
                        tr_id,
                        path,
                    )
                    self._force_reauth_current_env()
                    force_refreshed = True
                    continue

                res.raise_for_status()
                if not isinstance(data, dict):
                    data = res.json()
                if data.get("rt_cd") != "0":
                    logger.error("[KIS API] GET 실패: tr_id=%s msg=%s", tr_id, data.get("msg1"))
                return data
            except requests.exceptions.RequestException as exc:
                is_last_attempt = attempt >= _KIS_HTTP_GET_MAX_ATTEMPTS
                retryable = self._is_retryable_get_exception(exc)
                if not retryable or is_last_attempt:
                    logger.warning(
                        "[KIS API] GET 요청 실패: tr_id=%s path=%s attempt=%s/%s retryable=%s error=%s",
                        tr_id,
                        path,
                        attempt,
                        _KIS_HTTP_GET_MAX_ATTEMPTS,
                        retryable,
                        exc,
                    )
                    raise

                delay = self._get_retry_delay_seconds(attempt)
                logger.warning(
                    "[KIS API] GET 재시도 예정: tr_id=%s path=%s attempt=%s/%s backoff=%.2fs error=%s",
                    tr_id,
                    path,
                    attempt,
                    _KIS_HTTP_GET_MAX_ATTEMPTS,
                    delay,
                    exc,
                )
                time.sleep(delay)

        raise RuntimeError(f"unreachable KIS GET retry flow: tr_id={tr_id} path={path}")

    def _post(self, path: str, tr_id: str, body: dict) -> dict:
        url = f"{self._base_url()}{path}"
        force_refreshed = False

        while True:
            if getattr(self, "_direct_credentials", None) is None:
                self._core._ensure_auth()
            headers = self._headers(tr_id)
            if getattr(self, "_direct_credentials", None) is None:
                if self._ka is None:
                    raise RuntimeError("KIS adapter is not initialized")
                self._ka.set_order_hash_key(headers, body)
            else:
                self._set_direct_order_hash_key(headers, body)
            self._throttle_rest()
            try:
                res = self._session.post(
                    url,
                    headers=headers,
                    data=json.dumps(body),
                    timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
                )
            except requests.exceptions.RequestException as exc:
                logger.warning(
                    "[KIS API] POST 전송 실패: tr_id=%s path=%s error=%s",
                    tr_id,
                    path,
                    exc,
                )
                raise

            data = res.json() if "json" in dir(res) else None
            if self._is_expired_token_response(res, data=data):
                if force_refreshed:
                    res.raise_for_status()
                logger.warning(
                    "[KIS API] POST 응답에서 만료 토큰 감지; 강제 재인증 후 재시도 tr_id=%s path=%s",
                    tr_id,
                    path,
                )
                self._force_reauth_current_env()
                force_refreshed = True
                continue

            res.raise_for_status()
            if not isinstance(data, dict):
                data = res.json()
            if data.get("rt_cd") != "0":
                logger.error("[KIS API] POST 실패: tr_id=%s msg=%s", tr_id, data.get("msg1"))
            return data

    def _set_direct_order_hash_key(self, headers: dict[str, str], body: dict) -> None:
        response = self._session.post(
            f"{self._base_url()}/uapi/hashkey",
            headers=headers,
            data=json.dumps(body),
            timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
        )
        data = response.json()
        if self._is_expired_token_response(response, data=data):
            self._force_reauth_current_env()
            headers.update(self._headers(str(headers.get("tr_id") or "")))
            response = self._session.post(
                f"{self._base_url()}/uapi/hashkey",
                headers=headers,
                data=json.dumps(body),
                timeout=(_KIS_HTTP_CONNECT_TIMEOUT_SEC, _KIS_HTTP_READ_TIMEOUT_SEC),
            )
            data = response.json()
        response.raise_for_status()
        hash_value = data.get("HASH")
        if hash_value:
            headers["hashkey"] = str(hash_value)


class KISTradingAPI(KISMarketDataMixin, KISAccountTradingMixin, KISTradingBase):
    """KIS OpenAPI 기반 TradingAPI 프로토콜 구현체."""


def create_trading_api(credentials: KISDirectCredentials | None = None) -> KISTradingAPI:
    """
    Trading engine이 호출하는 팩토리 함수.

    사용법:
        TRADING_ENGINE_API_FACTORY=backend.integrations.kis.trading_adapter:create_trading_api
    """
    logger.info("[KIS TradingAPI] 팩토리 함수 호출 → KISTradingAPI 생성")
    return KISTradingAPI(credentials=credentials)
