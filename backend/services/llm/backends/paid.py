import logging
from typing import List, Optional

import httpx

from .base import LLMBackend
from ..config import Settings

logger = logging.getLogger(__name__)


class OpenAIPaidBackend(LLMBackend):
    """
    OpenAI 유료 API 백엔드 (Chat Completions -> Responses fallback)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = httpx.Client(timeout=settings.llm_timeout)
        self._last_error: Optional[str] = None

    def get_last_error(self) -> Optional[str]:
        return self._last_error

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
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)

    def chat(
        self,
        messages: List[dict],
        max_tokens: int = 1024,
        temperature: float = 0.5,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        **kwargs,
    ) -> str:
        api_key = self.settings.ai_report_api_key
        if not api_key:
            self._last_error = "AI_REPORT_API_KEY is not set"
            return ""

        model = kwargs.get("model") or self.settings.ai_report_model
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        is_gpt5 = str(model).startswith("gpt-5")

        # 1) Chat Completions 시도
        try:
            url = f"{self.settings.ai_report_base_url}/chat/completions"
            payload = {"model": model, "messages": messages}
            if not is_gpt5:
                payload["temperature"] = temperature
            payload["max_completion_tokens" if is_gpt5 else "max_tokens"] = max_tokens

            r = self._client.post(url, json=payload, headers=headers)
            if r.status_code < 400:
                self._last_error = None
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.debug("Chat completions failed, trying responses: %s", e)

        # 2) Responses API 시도 (GPT-5 등 지원)
        try:
            url = f"{self.settings.ai_report_base_url}/responses"
            payload = {
                "model": model,
                "input": [
                    {"role": m["role"], "content": [{"type": "input_text", "text": str(m["content"])}]}
                    for m in messages
                ],
                "max_output_tokens": max_tokens,
            }
            if is_gpt5:
                payload["reasoning"] = {"effort": "low"}
            else:
                payload["temperature"] = temperature

            r = self._client.post(url, json=payload, headers=headers)
            if r.status_code < 400:
                data = r.json()
                if output := data.get("output_text"):
                    self._last_error = None
                    return output.strip()

                chunks = []
                for item in (data.get("output") or []):
                    for part in (item.get("content") or []):
                        if part.get("type") in ("text", "output_text"):
                            chunks.append(part.get("text", ""))
                self._last_error = None
                return "".join(chunks).strip()
        except Exception as e:
            self._last_error = f"Paid LLM total failure: {e}"
            logger.error(self._last_error)

        if not self._last_error:
            self._last_error = "Paid LLM request failed"
        return ""

    def is_loaded(self) -> bool:
        return bool(self.settings.ai_report_api_key)

    def reset(self) -> None:
        pass

