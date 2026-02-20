import logging
from typing import List, Optional

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None

import requests

from .base import LLMBackend
from ..config import Settings

logger = logging.getLogger(__name__)


class RemoteLlamaBackend(LLMBackend):
    """
    llama-server (OpenAI 호환 API) 백엔드
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._use_httpx = bool(httpx)
        if self._use_httpx:
            self._client = httpx.Client(timeout=settings.llm_timeout)  # type: ignore[union-attr]
        else:
            self._client = requests.Session()
        self._model_id_cache: Optional[str] = None
        self._last_error: Optional[str] = None

    def _get(self, url: str, headers: dict):
        if self._use_httpx:
            return self._client.get(url, headers=headers)
        return self._client.get(url, headers=headers, timeout=self.settings.llm_timeout)

    def _post(self, url: str, payload: dict, headers: dict):
        if self._use_httpx:
            return self._client.post(url, json=payload, headers=headers)
        return self._client.post(url, json=payload, headers=headers, timeout=self.settings.llm_timeout)

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def _base_url(self) -> Optional[str]:
        if not self.settings.llm_base_url:
            self._last_error = "LLM_BASE_URL is not set"
            return None
        return self.settings.llm_base_url.rstrip("/")

    def _get_model_id(self) -> str:
        if self._model_id_cache:
            return self._model_id_cache

        base_url = self._base_url()
        if not base_url:
            return "local-model"

        try:
            url = f"{base_url}/v1/models"
            headers = {"Content-Type": "application/json"}
            if self.settings.llm_api_key:
                headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

            r = self._get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            items = data.get("data") or []
            if items and isinstance(items[0], dict):
                model_id = items[0].get("id")
                if model_id:
                    self._model_id_cache = model_id
                    self._last_error = None
                    return model_id
        except Exception as e:
            self._last_error = f"Failed to fetch model id from remote: {e}"
            logger.warning(self._last_error)

        return "local-model"

    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
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
        temperature: float = 0.7,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        import time
        import random
        
        base_url = self._base_url()
        if not base_url:
            return ""

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                url = f"{base_url}/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
                if self.settings.llm_api_key:
                    headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"

                payload = {
                    "model": kwargs.get("model") or self._get_model_id(),
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "top_p": kwargs.get("top_p", 0.8),
                    "top_k": kwargs.get("top_k", 20),
                }
                if stop:
                    payload["stop"] = stop

                # enable_thinking 처리 (명시적 True가 아니면 False로 설정하여 CoT 생성을 억제)
                enable_thinking = kwargs.get("enable_thinking", False)
                payload["chat_template_kwargs"] = {"enable_thinking": bool(enable_thinking)}

                r = self._post(url, payload=payload, headers=headers)
                r.raise_for_status()
                self._last_error = None
                
                resp_json = r.json()
                content = resp_json["choices"][0]["message"].get("content", "").strip()
                return content
            except Exception as e:
                # DNS 에러(socket.gaierror)나 연결 실패 시 재시도
                is_last = (attempt == max_attempts - 1)
                err_msg = str(e).lower()
                
                # 재시도 대상: DNS 에러(gaierror), 연결 에러, 타임아웃
                retryable = any(x in err_msg for x in ["gaierror", "connection", "connect", "timeout"])
                
                if retryable and not is_last:
                    wait_time = (2 ** attempt) + random.random()
                    logger.warning(
                        f"Remote LLM connection error (attempt {attempt+1}/{max_attempts}): {e}. "
                        f"Retrying in {wait_time:.2f}s..."
                    )
                    time.sleep(wait_time)
                    continue
                    
                self._last_error = f"Remote LLM request failed: {e}"
                if "timeout" in err_msg:
                    logger.error("🚨 타임아웃 타임아웃 🚨 : Remote LLM timed out")
                logger.error(self._last_error)
                return ""

    def is_loaded(self) -> bool:
        return True

    def reset(self) -> None:
        pass
