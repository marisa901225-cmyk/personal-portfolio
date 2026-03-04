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


class OpenAIPaidBackend(LLMBackend):
    """
    OpenAI 유료 API 백엔드 (Chat Completions -> Responses fallback)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        # OpenAI Flex는 느릴 수 있으므로 설정된 타임아웃(기본 900초) 적용
        self._use_httpx = bool(httpx)
        if self._use_httpx:
            self._client = httpx.Client(timeout=settings.ai_report_timeout_sec)  # type: ignore[union-attr]
        else:
            self._client = requests.Session()
        self._last_error: Optional[str] = None

    def get_last_error(self) -> Optional[str]:
        return self._last_error

    def _post(self, url: str, payload: dict, headers: dict):
        if self._use_httpx:
            return self._client.post(url, json=payload, headers=headers)
        return self._client.post(url, json=payload, headers=headers, timeout=self.settings.ai_report_timeout_sec)

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
        return self.chat(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
            seed=seed,
            **kwargs,
        )

    def _convert_to_system_prompt(self, messages: List[dict]) -> List[dict]:
        """
        OpenAI 유료 모델용: 첫 user 메시지가 시스템 지시문 패턴이면 system role로 변환.
        로컬 LLM에서는 user role만 써도 되지만, OpenAI API는 system/user 분리가 중요.
        """
        import re
        if not messages:
            return messages
        
        first = messages[0]
        if first.get("role") != "user":
            return messages  # 이미 system이 있거나 다른 role이면 그대로
        
        content = first.get("content", "")
        if not content:
            return messages
        
        # 시스템 지시문 패턴 감지 (한글/영어)
        system_patterns = [
            r"^당신은\s+",        # 당신은 ~입니다
            r"^너는\s+",          # 너는 ~야
            r"^You are\s+",       # You are ~
            r"^\[?역할\]?",       # [역할] 또는 역할:
            r"^\[?지침\]?",       # [지침] 또는 지침:
            r"^\[?작성\s*지침\]?", # [작성 지침]
        ]
        
        is_system_like = any(re.match(p, content.strip(), re.IGNORECASE) for p in system_patterns)
        
        if not is_system_like:
            return messages
        
        # 시스템 프롬프트로 변환하고, 간단한 user 메시지 추가
        new_messages = [
            {"role": "system", "content": content},
            {"role": "user", "content": "위 지침대로 작성해주세요."}
        ]
        # 기존 메시지가 더 있으면 추가 (첫 번째만 변환)
        if len(messages) > 1:
            new_messages = [{"role": "system", "content": content}] + messages[1:]
        
        return new_messages

    def chat(
        self,
        messages: List[dict],
        max_tokens: int = 1024,
        temperature: float = 0.5,
        stop: Optional[list] = None,
        seed: Optional[int] = None,
        top_p: float = 0.8,
        top_k: int = 20,
        **kwargs,
    ) -> str:
        import time
        import random

        # OpenAI 유료 모델용 시스템 프롬프트 자동 분리
        messages = self._convert_to_system_prompt(messages)

        api_key = kwargs.get("api_key") or self.settings.ai_report_api_key
        base_url = kwargs.get("base_url") or self.settings.ai_report_base_url

        if not api_key:
            self._last_error = "AI_REPORT_API_KEY is not set"
            return ""

        model = kwargs.get("model") or self.settings.ai_report_model
        service_tier = kwargs.get("service_tier")
        response_format = kwargs.get("response_format")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        is_gpt5 = str(model).startswith("gpt-5") or "gpt-5" in str(model)

        max_attempts = 5 if service_tier == "flex" else 1
        current_tier = service_tier

        def _safe_error_message(resp) -> str:
            try:
                data = resp.json() or {}
                if isinstance(data, dict):
                    err = data.get("error") or {}
                    if isinstance(err, dict):
                        msg = err.get("message")
                        if msg:
                            return str(msg)
                return str(data)[:500]
            except Exception:
                return (getattr(resp, "text", "") or "").strip()[:500]

        def _should_try_responses(status_code: int, error_msg: str) -> bool:
            if not error_msg:
                return False
            msg = error_msg.lower()
            if "responses" in msg:
                return True
            if "chat/completions" in msg and ("not supported" in msg or "does not support" in msg):
                return True
            if status_code in (404, 405) and "not found" in msg and "chat" in msg:
                return True
            # GPT-5 계열은 Chat Completions 미지원인 경우가 있으므로, 모델 오류면 Responses를 시도
            if is_gpt5 and status_code in (400, 404) and ("model" in msg or "not supported" in msg):
                return True
            return False

        def _try_responses() -> str:
            url = f"{base_url.rstrip('/')}/responses"
            responses_text_format = None
            if isinstance(response_format, dict):
                rft = response_format.get("type")
                if rft == "json_schema":
                    js = response_format.get("json_schema")
                    if isinstance(js, dict):
                        fmt = {"type": "json_schema"}
                        if "name" in js:
                            fmt["name"] = js["name"]
                        if "schema" in js:
                            fmt["schema"] = js["schema"]
                        if "strict" in js:
                            fmt["strict"] = js["strict"]
                        responses_text_format = fmt
                elif rft == "json_object":
                    responses_text_format = {"type": "json_object"}

            payload = {
                "model": model,
                "input": [
                    {"role": m["role"], "content": [{"type": "input_text", "text": str(m["content"])}]}
                    for m in messages
                ],
                "max_output_tokens": max_tokens,
            }
            if responses_text_format:
                payload["text"] = {"format": responses_text_format}
            if is_gpt5:
                # GPT-5 계열은 low에서도 reasoning token만 소진되는 경우가 있어 minimal로 고정
                payload["reasoning"] = {"effort": "minimal"}
            else:
                payload["temperature"] = temperature
            if stop and not is_gpt5:
                payload["stop"] = stop
            if seed is not None:
                payload["seed"] = seed
            # Responses API does not support top_p in some cases, causing 400 error
            # if top_p is not None:
            #     payload["top_p"] = top_p
            if current_tier:
                payload["service_tier"] = current_tier

            r = self._post(url, payload=payload, headers=headers)
            if r.status_code >= 400:
                error_msg = _safe_error_message(r)
                self._last_error = f"OpenAI Responses API error {r.status_code}: {error_msg}"
                logger.error(self._last_error)
                return ""

            data = r.json() or {}
            if output := data.get("output_text"):
                self._last_error = None
                return str(output).strip()

            chunks = []
            for item in (data.get("output") or []):
                if item.get("type") == "message":
                    for part in (item.get("content") or []):
                        if part.get("type") in ("text", "output_text"):
                            chunks.append(part.get("text", ""))

            if chunks:
                self._last_error = None
                return "".join(chunks).strip()

            self._last_error = "OpenAI Responses API returned no output text"
            logger.error(self._last_error)
            return ""

        def _extract_chat_content(data: dict) -> str:
            choices = data.get("choices") or []
            first = choices[0] if choices else {}
            msg = first.get("message") or {}
            raw_content = msg.get("content")

            if isinstance(raw_content, str):
                return raw_content.strip()

            if isinstance(raw_content, list):
                parts = []
                for part in raw_content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") in ("text", "output_text"):
                        txt = part.get("text")
                        if txt:
                            parts.append(str(txt))
                return "".join(parts).strip()

            return ""

        for attempt in range(max_attempts):
            try:
                # 1) Chat Completions 시도 (기본)
                url = f"{base_url.rstrip('/')}/chat/completions"
                payload = {"model": model, "messages": messages}
                if not is_gpt5:
                    payload["temperature"] = temperature
                payload["max_completion_tokens" if is_gpt5 else "max_tokens"] = max_tokens
                if stop:
                    payload["stop"] = stop
                if seed is not None:
                    payload["seed"] = seed
                if top_p is not None and not is_gpt5:
                    payload["top_p"] = top_p
                if response_format:
                    payload["response_format"] = response_format
                
                if current_tier:
                    payload["service_tier"] = current_tier

                r = self._post(url, payload=payload, headers=headers)
                
                # 에러 핸들링
                if r.status_code >= 400:
                    error_msg = _safe_error_message(r)
                    
                    # Flex 미가용 시 즉시 표준 티어로 폴백
                    if "is not available for this model" in error_msg and current_tier == "flex":
                        logger.warning(f"Flex tier not available for {model}. Falling back to standard.")
                        current_tier = None
                        # 폴백 시 바로 다음 루프에서 재시도
                        continue

                    # 재시도 대상 에러 (429 Too Many Requests, 5xx Server Error)
                    if r.status_code == 429 or r.status_code >= 500:
                        if attempt < max_attempts - 1:
                            wait_time = (2 ** attempt) + random.random()
                            logger.warning(f"OpenAI API error {r.status_code} (attempt {attempt+1}/{max_attempts}). Retrying in {wait_time:.2f}s...")
                            time.sleep(wait_time)
                            continue
                    
                    if _should_try_responses(r.status_code, error_msg):
                        out = _try_responses()
                        if out:
                            return out
                        # Responses도 실패했으면 last_error는 _try_responses에서 세팅됨
                        return ""

                    self._last_error = f"OpenAI Chat Completions API error {r.status_code}: {error_msg}"
                    logger.error(self._last_error)
                    return ""

                # 성공 시 결과 처리
                data = r.json() or {}
                content = _extract_chat_content(data)
                actual_tier = data.get("service_tier", "standard") # 응답에서 실제 티어 확인
                logger.info(f"OpenAI API Success. Model: {model}, Requested Tier: {current_tier}, Actual Tier: {actual_tier}")

                if content:
                    self._last_error = None
                    return content

                # GPT-5 계열에서 reasoning token만 소진되고 content가 비는 경우가 있어 Responses로 폴백
                choices = data.get("choices") or []
                first = choices[0] if choices else {}
                finish_reason = first.get("finish_reason")
                usage = data.get("usage") or {}
                completion_details = usage.get("completion_tokens_details") or {}
                reasoning_tokens = completion_details.get("reasoning_tokens")
                logger.warning(
                    "OpenAI Chat Completions returned empty content; trying Responses fallback "
                    "(model=%s, finish_reason=%s, reasoning_tokens=%s)",
                    model,
                    finish_reason,
                    reasoning_tokens,
                )
                out = _try_responses()
                if out:
                    return out
                self._last_error = (
                    "OpenAI Chat Completions returned empty content "
                    f"(finish_reason={finish_reason}, reasoning_tokens={reasoning_tokens})"
                )
                logger.error(self._last_error)
                return ""

            except Exception as e:
                # 2) Chat Completions가 예외로 실패한 경우: 마지막 시도에서 Responses 폴백
                if attempt == max_attempts - 1:
                    logger.debug("Chat completions totally failed, trying responses fallback: %s", e)
                    out = _try_responses()
                    if out:
                        return out
                    self._last_error = self._last_error or f"Paid LLM total failure: {e}"
                    logger.error(self._last_error)

        return ""

    def is_loaded(self) -> bool:
        return bool(self.settings.ai_report_api_key)

    def reset(self) -> None:
        pass
