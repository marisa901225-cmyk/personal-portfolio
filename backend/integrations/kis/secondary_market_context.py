from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from backend.core.config import settings
from backend.integrations.kis.config_paths import get_kis_config_dir
from backend.integrations.kis.rest_rate_limiter import (
    throttle_rest_min_gap,
    throttle_rest_requests,
)
from backend.integrations.kis.token_store import read_kis_token_record, save_kis_token

logger = logging.getLogger(__name__)

_HTTP_CONNECT_TIMEOUT_SEC = 3.05
_HTTP_READ_TIMEOUT_SEC = 10.0
_HTTP_GET_MAX_ATTEMPTS = 3
_HTTP_RETRY_BACKOFF_SEC = 0.35
_HTTP_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_AUTH_EXPIRY_BUFFER_SEC = 60
_DEFAULT_PROD_URL = "https://openapi.koreainvestment.com:9443"

_EXPIRED_TOKEN_MESSAGE_CODES = {"EGW00123"}
_EXPIRED_TOKEN_MESSAGE_SNIPPETS = (
    "기간이 만료된 token",
    "token expired",
    "expired token",
)


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _is_expired_token_response(
    response: requests.Response,
    *,
    data: dict[str, Any] | None = None,
) -> bool:
    payload = data if isinstance(data, dict) else {}
    msg_cd = _safe_text(payload.get("msg_cd"))
    msg1 = _safe_text(payload.get("msg1"))
    combined = " ".join(
        part for part in (msg_cd, msg1, getattr(response, "text", "") or "") if part
    ).lower()

    if msg_cd in _EXPIRED_TOKEN_MESSAGE_CODES:
        return True
    if any(snippet.lower() in combined for snippet in _EXPIRED_TOKEN_MESSAGE_SNIPPETS):
        return True
    if response.status_code == 401 and "token" in combined:
        return True
    return False


def _is_retryable_get_exception(exc: requests.exceptions.RequestException) -> bool:
    if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
        return True

    if isinstance(exc, requests.exceptions.HTTPError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        return status_code in _HTTP_RETRYABLE_STATUS

    return False


def _retry_delay_seconds(attempt: int) -> float:
    return _HTTP_RETRY_BACKOFF_SEC * (2 ** max(0, attempt - 1))


@dataclass(slots=True)
class SecondaryMarketCredentials:
    app_key: str
    app_secret: str
    product: str
    base_url: str
    user_agent: str


class SecondaryMarketContext:
    """Read-only KIS REST context for market-data fan-out."""

    _TOKEN_SLOT = 1

    def __init__(
        self,
        credentials: SecondaryMarketCredentials,
        *,
        config_dir: Path,
        min_gap_by_path: dict[str, float] | None = None,
    ) -> None:
        self._credentials = credentials
        self._config_dir = Path(config_dir)
        self._session = requests.Session()
        self._auth_lock = threading.Lock()
        self._access_token: str | None = None
        self._access_token_expires_at: datetime | None = None
        self._min_gap_by_path = dict(min_gap_by_path or {})

    def _base_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "text/plain",
            "charset": "UTF-8",
            "User-Agent": self._credentials.user_agent,
        }

    def _request_headers(self, tr_id: str, tr_cont: str = "") -> dict[str, str]:
        token = self.ensure_auth()
        headers = self._base_headers()
        headers["authorization"] = f"Bearer {token}"
        headers["appkey"] = self._credentials.app_key
        headers["appsecret"] = self._credentials.app_secret
        headers["tr_id"] = tr_id
        headers["custtype"] = "P"
        if tr_cont:
            headers["tr_cont"] = tr_cont
        return headers

    def _token_is_valid(self) -> bool:
        if not self._access_token:
            return False
        if self._access_token_expires_at is None:
            return True
        return datetime.now() + timedelta(seconds=_AUTH_EXPIRY_BUFFER_SEC) < self._access_token_expires_at

    def ensure_auth(self, *, force: bool = False) -> str:
        with self._auth_lock:
            if not force and self._token_is_valid():
                return str(self._access_token)

            if not force:
                cached_token, cached_expires_at = read_kis_token_record(slot=self._TOKEN_SLOT)
                if cached_token:
                    self._access_token = cached_token
                    self._access_token_expires_at = cached_expires_at
                    if self._token_is_valid():
                        logger.info(
                            "secondary KIS market-data token reused from DB (expires_at=%s)",
                            cached_expires_at.isoformat(sep=" ", timespec="seconds")
                            if cached_expires_at
                            else "unknown",
                        )
                        return cached_token

            payload = {
                "grant_type": "client_credentials",
                "appkey": self._credentials.app_key,
                "appsecret": self._credentials.app_secret,
            }
            url = f"{self._credentials.base_url}/oauth2/tokenP"

            throttle_rest_requests(config_dir=self._config_dir)
            response = self._session.post(
                url,
                data=json.dumps(payload),
                headers=self._base_headers(),
                timeout=(_HTTP_CONNECT_TIMEOUT_SEC, _HTTP_READ_TIMEOUT_SEC),
            )
            response.raise_for_status()
            data = response.json()
            token = _safe_text(data.get("access_token"))
            if not token:
                raise RuntimeError("secondary KIS auth response missing access_token")

            expiry_raw = _safe_text(data.get("access_token_token_expired"))
            expiry_at = None
            if expiry_raw:
                try:
                    expiry_at = datetime.strptime(expiry_raw, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    logger.warning("secondary KIS token expiry parse failed: %s", expiry_raw)

            self._access_token = token
            self._access_token_expires_at = expiry_at
            save_kis_token(token, expiry_at, slot=self._TOKEN_SLOT)
            logger.info(
                "secondary KIS market-data auth refreshed (expires_at=%s)",
                expiry_at.isoformat(sep=" ", timespec="seconds") if expiry_at else "unknown",
            )
            return token

    def _throttle_path_min_gap(self, path: str) -> None:
        min_gap_sec = self._min_gap_by_path.get(_safe_text(path))
        if not min_gap_sec:
            return
        throttle_rest_min_gap(
            scope=f"kis_get:{path}",
            min_gap_sec=float(min_gap_sec),
            config_dir=self._config_dir,
        )

    def get(self, path: str, tr_id: str, params: dict[str, Any], tr_cont: str = "") -> dict[str, Any]:
        url = f"{self._credentials.base_url}{path}"
        force_refreshed = False

        for attempt in range(1, _HTTP_GET_MAX_ATTEMPTS + 1):
            headers = self._request_headers(tr_id, tr_cont)
            throttle_rest_requests(config_dir=self._config_dir)
            self._throttle_path_min_gap(path)

            try:
                response = self._session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=(_HTTP_CONNECT_TIMEOUT_SEC, _HTTP_READ_TIMEOUT_SEC),
                )
                data = response.json() if hasattr(response, "json") else None
                if _is_expired_token_response(response, data=data if isinstance(data, dict) else None):
                    if force_refreshed:
                        response.raise_for_status()
                    logger.warning(
                        "[KIS secondary] expired token detected; refreshing and retrying tr_id=%s path=%s",
                        tr_id,
                        path,
                    )
                    self.ensure_auth(force=True)
                    force_refreshed = True
                    continue

                response.raise_for_status()
                if not isinstance(data, dict):
                    data = response.json()
                return data
            except requests.exceptions.RequestException as exc:
                is_last_attempt = attempt >= _HTTP_GET_MAX_ATTEMPTS
                retryable = _is_retryable_get_exception(exc)
                if not retryable or is_last_attempt:
                    raise
                time.sleep(_retry_delay_seconds(attempt))

        raise RuntimeError(f"unreachable secondary KIS GET retry flow: tr_id={tr_id} path={path}")


def build_secondary_market_context(
    *,
    min_gap_by_path: dict[str, float] | None = None,
) -> SecondaryMarketContext | None:
    app_key = _safe_text(settings.kis_my_app1)
    app_secret = _safe_text(settings.kis_my_sec1)
    if not app_key or not app_secret:
        return None

    product = _safe_text(settings.kis_my_prod1) or _safe_text(settings.kis_my_prod) or "01"
    base_url = _safe_text(settings.kis_prod) or _DEFAULT_PROD_URL
    user_agent = _safe_text(settings.kis_my_agent) or "MyAsset"
    config_dir = get_kis_config_dir() / "slot1_market"

    credentials = SecondaryMarketCredentials(
        app_key=app_key,
        app_secret=app_secret,
        product=product,
        base_url=base_url,
        user_agent=user_agent,
    )
    return SecondaryMarketContext(
        credentials,
        config_dir=config_dir,
        min_gap_by_path=min_gap_by_path,
    )


__all__ = [
    "SecondaryMarketContext",
    "SecondaryMarketCredentials",
    "build_secondary_market_context",
]
