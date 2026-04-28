from __future__ import annotations

import logging
import random
import socket
import time
from typing import Any, Dict, List, Optional

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None

import requests
from requests import exceptions as req_exc

from .base import LLMBackend
from ..config import Settings

logger = logging.getLogger(__name__)


class RemoteLlamaBackend(LLMBackend):
    """
    llama-server (OpenAI 호환 API) 백엔드
    - /v1/models 로 모델 id 자동 탐색(캐시)
    - /v1/chat/completions 로 chat 호출
    - 네트워크/타임아웃/일부 5xx/429 등에 대해 지수 백오프 재시도
    """

    DEFAULT_MODEL_ID = "local-model"
    MAX_ATTEMPTS = 3
    RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self, settings: Settings):
        self.settings = settings
        self._use_httpx = bool(httpx)

        if self._use_httpx:
            self._client = httpx.Client(timeout=settings.llm_timeout)  # type: ignore[union-attr]
        else:
            self._client = requests.Session()

        self._model_id_cache: Dict[str, str] = {}
        self._last_error: Optional[str] = None
        self._last_token_metrics: Optional[Dict[str, int]] = None

    def close(self) -> None:
        """프로세스 종료나 테스트에서 명시적으로 닫고 싶을 때."""
        try:
            self._client.close()
        except Exception:
            pass

    def __del__(self) -> None:  # pragma: no cover
        self.close()

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def reset(self) -> None:
        """캐시/에러 상태 초기화."""
        self._model_id_cache = {}
        self._last_error = None
        self._last_token_metrics = None

    def is_loaded(self) -> bool:
        return True

    def clear_last_token_metrics(self) -> None:
        self._last_token_metrics = None

    def consume_last_token_metrics(self) -> Optional[Dict[str, int]]:
        metrics = self._last_token_metrics
        self._last_token_metrics = None
        return metrics

    # -------------------------
    # Internal helpers
    # -------------------------

    def _base_url(self, override: Optional[str] = None) -> Optional[str]:
        base = (override or self.settings.llm_base_url or "").strip()
        if not base:
            self._last_error = "LLM_BASE_URL is not set"
            return None
        return base.rstrip("/")

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        return headers

    def _request(self, method: str, url: str, *, payload: Optional[dict] = None) -> Any:
        headers = self._headers()
        if self._use_httpx:
            # httpx.Client는 생성 시 timeout이 걸려있음
            return self._client.request(method, url, headers=headers, json=payload)
        # requests는 매 호출마다 timeout 지정
        return self._client.request(method, url, headers=headers, json=payload, timeout=self.settings.llm_timeout)

    def _is_retryable_exception(self, e: Exception) -> bool:
        # DNS
        if isinstance(e, socket.gaierror):
            return True

        # httpx 예외
        if self._use_httpx and httpx is not None:
            # RequestError: ConnectError/ReadError 등 네트워크 계열 포함
            if isinstance(e, (httpx.TimeoutException, httpx.RequestError)):
                return True

        # requests 예외
        if isinstance(e, (req_exc.Timeout, req_exc.ConnectionError)):
            return True

        return False

    def _is_retryable_http_error(self, e: Exception) -> bool:
        # httpx HTTPStatusError
        if self._use_httpx and httpx is not None and isinstance(e, httpx.HTTPStatusError):
            try:
                return int(e.response.status_code) in self.RETRYABLE_STATUS
            except Exception:
                return False

        # requests HTTPError
        if isinstance(e, req_exc.HTTPError):
            try:
                if e.response is None:
                    return False
                return int(e.response.status_code) in self.RETRYABLE_STATUS
            except Exception:
                return False

        return False

    def _request_json_with_retries(self, method: str, url: str, *, payload: Optional[dict] = None) -> dict:
        last_exc: Optional[Exception] = None

        for attempt in range(self.MAX_ATTEMPTS):
            is_last = (attempt == self.MAX_ATTEMPTS - 1)

            try:
                r = self._request(method, url, payload=payload)
                r.raise_for_status()
                data = r.json()
                self._last_error = None
                return data

            except Exception as e:
                last_exc = e
                retryable = self._is_retryable_exception(e) or self._is_retryable_http_error(e)

                if retryable and not is_last:
                    wait = (2 ** attempt) + random.random()  # 지수 백오프 + 지터
                    logger.warning(
                        f"Remote LLM request error (attempt {attempt+1}/{self.MAX_ATTEMPTS}): {e}. "
                        f"Retrying in {wait:.2f}s..."
                    )
                    time.sleep(wait)
                    continue

                # 마지막 실패
                raise

        # 이론상 도달하지 않지만, mypy/안전장치
        raise RuntimeError(f"Remote request failed: {last_exc}")

    def _get_model_id(self, base_url: Optional[str] = None) -> str:
        resolved_base_url = (base_url or "").rstrip("/") if base_url else self._base_url()
        if not resolved_base_url:
            return self.DEFAULT_MODEL_ID

        cached_model_id = self._model_id_cache.get(resolved_base_url)
        if cached_model_id:
            return cached_model_id

        url = f"{resolved_base_url}/v1/models"
        try:
            data = self._request_json_with_retries("GET", url)
            items = data.get("data") or []
            if items and isinstance(items[0], dict):
                model_id = items[0].get("id")
                if model_id:
                    self._model_id_cache[resolved_base_url] = str(model_id)
                    self._last_error = None
                    return self._model_id_cache[resolved_base_url]
        except Exception as e:
            self._last_error = f"Failed to fetch model id from remote: {e}"
            logger.warning(self._last_error)

        return self.DEFAULT_MODEL_ID

    def _extract_content(self, resp_json: dict) -> str:
        """
        OpenAI 호환 응답에서 content 추출.
        서버/프록시가 변형해도 최대한 안전하게 처리.
        """
        try:
            choices = resp_json.get("choices") or []
            if not choices:
                return ""
            msg = (choices[0] or {}).get("message") or {}
            content = (msg.get("content") or "").strip()
            return content
        except Exception:
            return ""

    def _extract_token_metrics(self, resp_json: dict) -> Optional[Dict[str, int]]:
        metrics: Dict[str, int] = {}

        try:
            usage = resp_json.get("usage")
            if isinstance(usage, dict):
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = usage.get(key)
                    if isinstance(value, (int, float)):
                        metrics[key] = int(value)
                if "total_tokens" not in metrics and {"prompt_tokens", "completion_tokens"} <= set(metrics):
                    metrics["total_tokens"] = metrics["prompt_tokens"] + metrics["completion_tokens"]
        except Exception:
            pass

        try:
            timings = resp_json.get("timings")
            if isinstance(timings, dict):
                cache_n = timings.get("cache_n")
                prompt_n = timings.get("prompt_n")
                predicted_n = timings.get("predicted_n")
                if all(isinstance(value, (int, float)) for value in (cache_n, prompt_n, predicted_n)):
                    metrics["context_tokens"] = int(cache_n) + int(prompt_n) + int(predicted_n)
        except Exception:
            pass

        return metrics or None

    def _resolve_slot_id(self, base_url: str, preferred_slot_id: int = 0) -> int:
        url = f"{base_url}/slots"
        try:
            data = self._request_json_with_retries("GET", url)
            if isinstance(data, list):
                for slot in data:
                    if isinstance(slot, dict) and int(slot.get("id", -1)) == preferred_slot_id:
                        return preferred_slot_id
                if data and isinstance(data[0], dict):
                    first_id = data[0].get("id")
                    if isinstance(first_id, (int, float)):
                        return int(first_id)
        except Exception as e:
            logger.warning("Failed to resolve llama slot id from %s: %s", url, e)
        return preferred_slot_id

    def reset_context(self, slot_id: int = 0, *, base_url_override: Optional[str] = None) -> bool:
        base_url = self._base_url(base_url_override)
        if not base_url:
            return False

        resolved_slot_id = self._resolve_slot_id(base_url, preferred_slot_id=slot_id)
        url = f"{base_url}/slots/{resolved_slot_id}?action=erase"

        try:
            self._request_json_with_retries("POST", url, payload={})
            self._last_error = None
            self._last_token_metrics = None
            logger.info("Remote llama slot reset succeeded (slot=%s).", resolved_slot_id)
            return True
        except Exception as e:
            self._last_error = f"Remote llama slot reset failed: {e}"
            logger.warning("%s (url=%s)", self._last_error, url)
            return False

    # -------------------------
    # Public API
    # -------------------------

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 1.0,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature, stop=stop, seed=seed, **kwargs)

    def chat(
        self,
        messages: List[dict],
        max_tokens: int = 512,
        temperature: float = 1.0,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        self._last_token_metrics = None
        base_url = self._base_url(kwargs.get("base_url_override"))
        if not base_url:
            return ""

        url = f"{base_url}/v1/chat/completions"

        model = kwargs.get("model") or self._get_model_id(base_url)
        top_p = kwargs.get("top_p", 0.95)
        top_k = kwargs.get("top_k", 64)
        enable_thinking = bool(kwargs.get("enable_thinking", False))

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": int(max_tokens),
            "temperature": float(temperature),
            "top_p": top_p,
            "top_k": top_k,
            # CoT 억제 목적: 명시적으로 True일 때만 켬
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        }

        if stop:
            payload["stop"] = stop
        if seed is not None:
            payload["seed"] = int(seed)

        # 필요 시 추가 OpenAI 호환 파라미터를 허용(안전한 것만)
        passthrough_keys = ("presence_penalty", "frequency_penalty", "logit_bias", "response_format")
        for k in passthrough_keys:
            if k in kwargs:
                payload[k] = kwargs[k]

        try:
            resp = self._request_json_with_retries("POST", url, payload=payload)
            self._last_token_metrics = self._extract_token_metrics(resp)
            content = self._extract_content(resp)
            if not content:
                # 빈 content면 원인 추적용 에러만 남기고 반환은 빈 문자열 유지
                self._last_error = f"Remote LLM returned empty content. resp_keys={list(resp.keys())}"
                logger.warning(self._last_error)
            else:
                self._last_error = None
            return content
        except Exception as e:
            err_lower = str(e).lower()
            self._last_error = f"Remote LLM request failed: {e}"
            if "timeout" in err_lower:
                logger.error("Remote LLM timed out.")
            logger.error(self._last_error)
            return ""
