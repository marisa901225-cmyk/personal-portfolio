import logging
from typing import Any, Dict, List, Optional

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None

import requests

from .base import LLMBackend
from ..config import Settings

logger = logging.getLogger(__name__)
_DEFAULT_GPT5_REASONING_EFFORT = "medium"
_ALLOWED_GPT5_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh"}


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

    @staticmethod
    def _is_gpt5_model(model: Optional[str]) -> bool:
        model_name = str(model or "")
        return model_name.startswith("gpt-5") or "gpt-5" in model_name

    @staticmethod
    def _extract_message_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            chunks: List[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if text:
                    chunks.append(str(text))
            return "".join(chunks).strip()

        return ""

    def _safe_error_message(self, resp) -> str:
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

    def _should_try_responses(self, status_code: int, error_msg: str, *, is_gpt5: bool) -> bool:
        if not error_msg:
            return False

        msg = error_msg.lower()
        if "responses" in msg:
            return True
        if "chat/completions" in msg and ("not supported" in msg or "does not support" in msg):
            return True
        if status_code in (404, 405) and "not found" in msg and "chat" in msg:
            return True
        if is_gpt5 and status_code in (400, 404) and ("model" in msg or "not supported" in msg):
            return True
        return False

    @staticmethod
    def _build_responses_text_format(response_format: Any) -> Optional[dict]:
        if not isinstance(response_format, dict):
            return None

        response_type = response_format.get("type")
        if response_type == "json_schema":
            json_schema = response_format.get("json_schema")
            if not isinstance(json_schema, dict):
                return None

            fmt: Dict[str, Any] = {"type": "json_schema"}
            if "name" in json_schema:
                fmt["name"] = json_schema["name"]
            if "schema" in json_schema:
                fmt["schema"] = json_schema["schema"]
            if "strict" in json_schema:
                fmt["strict"] = json_schema["strict"]
            return fmt

        if response_type == "json_object":
            return {"type": "json_object"}

        return None

    @staticmethod
    def _resolve_gpt5_reasoning_effort(reasoning_effort: Optional[str]) -> str:
        effort = str(reasoning_effort or "").strip().lower()
        if effort in _ALLOWED_GPT5_REASONING_EFFORTS:
            return effort
        return _DEFAULT_GPT5_REASONING_EFFORT

    def _build_chat_payload(
        self,
        *,
        model: str,
        messages: List[dict],
        max_tokens: int,
        temperature: float,
        stop: Optional[list],
        seed: Optional[int],
        top_p: float,
        response_format: Any,
        current_tier: Optional[str],
        is_gpt5: bool,
    ) -> dict:
        payload: Dict[str, Any] = {"model": model, "messages": messages}
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
        return payload

    def _extract_chat_output(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            return ""

        message = (choices[0].get("message") or {}) if isinstance(choices[0], dict) else {}
        return self._extract_message_text(message.get("content"))

    def _build_responses_payload(
        self,
        *,
        model: str,
        messages: List[dict],
        max_tokens: int,
        temperature: float,
        stop: Optional[list],
        seed: Optional[int],
        current_tier: Optional[str],
        response_format: Any,
        is_gpt5: bool,
        reasoning_effort: Optional[str],
    ) -> dict:
        responses_max_tokens = max(int(max_tokens), 16)
        payload: Dict[str, Any] = {
            "model": model,
            "input": [
                {"role": str(msg.get("role") or "user"), "content": self._build_responses_input_content(msg.get("content"))}
                for msg in messages
            ],
            # OpenAI Responses API는 매우 작은 값에서 400을 반환할 수 있어 하한을 맞춘다.
            "max_output_tokens": responses_max_tokens,
        }

        responses_text_format = self._build_responses_text_format(response_format)
        if responses_text_format:
            payload["text"] = {"format": responses_text_format}

        if is_gpt5:
            payload["reasoning"] = {"effort": self._resolve_gpt5_reasoning_effort(reasoning_effort)}
        else:
            payload["temperature"] = temperature

        if stop and not is_gpt5:
            payload["stop"] = stop
        if seed is not None:
            payload["seed"] = seed
        if current_tier:
            payload["service_tier"] = current_tier

        return payload

    @staticmethod
    def _build_responses_input_content(content: Any) -> List[dict]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]

        if not isinstance(content, list):
            return [{"type": "input_text", "text": str(content)}]

        items: List[dict] = []
        for part in content:
            if isinstance(part, str):
                items.append({"type": "input_text", "text": part})
                continue
            if not isinstance(part, dict):
                continue

            part_type = str(part.get("type") or "").strip().lower()
            if part_type in {"text", "input_text"}:
                text = part.get("text")
                if text is not None:
                    items.append({"type": "input_text", "text": str(text)})
                continue

            if part_type in {"image_url", "input_image"}:
                raw_image = part.get("image_url")
                image_url: str | None = None
                if isinstance(raw_image, dict):
                    image_url = raw_image.get("url") or raw_image.get("image_url")
                elif raw_image:
                    image_url = str(raw_image)
                elif part.get("url"):
                    image_url = str(part.get("url"))
                if image_url:
                    image_part: Dict[str, Any] = {"type": "input_image", "image_url": image_url}
                    detail = part.get("detail")
                    if detail:
                        image_part["detail"] = detail
                    items.append(image_part)
                continue

        if items:
            return items
        return [{"type": "input_text", "text": ""}]

    def _extract_responses_output(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        output_text = data.get("output_text")
        if output_text:
            return str(output_text).strip()

        chunks: List[str] = []
        for item in (data.get("output") or []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in (item.get("content") or []):
                if not isinstance(part, dict):
                    continue
                if part.get("type") in ("text", "output_text") and part.get("text"):
                    chunks.append(str(part["text"]))
        return "".join(chunks).strip()

    def _try_responses_api(
        self,
        *,
        base_url: str,
        headers: dict,
        model: str,
        messages: List[dict],
        max_tokens: int,
        temperature: float,
        stop: Optional[list],
        seed: Optional[int],
        current_tier: Optional[str],
        response_format: Any,
        is_gpt5: bool,
        reasoning_effort: Optional[str],
    ) -> str:
        import random
        import time

        url = f"{base_url.rstrip('/')}/responses"
        payload = self._build_responses_payload(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop,
            seed=seed,
            current_tier=current_tier,
            response_format=response_format,
            is_gpt5=is_gpt5,
            reasoning_effort=reasoning_effort,
        )

        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = self._post(url, payload=payload, headers=headers)
            except Exception as exc:
                if attempt < max_attempts - 1:
                    wait_time = (2 ** attempt) + random.random()
                    logger.warning(
                        "OpenAI Responses request failed (attempt %s/%s). Retrying in %.2fs... error=%s",
                        attempt + 1,
                        max_attempts,
                        wait_time,
                        exc,
                    )
                    time.sleep(wait_time)
                    continue
                self._last_error = f"OpenAI Responses API request failed: {exc}"
                logger.error(self._last_error)
                return ""

            if response.status_code >= 400:
                error_msg = self._safe_error_message(response)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < max_attempts - 1:
                        wait_time = (2 ** attempt) + random.random()
                        logger.warning(
                            "OpenAI Responses API error %s (attempt %s/%s). Retrying in %.2fs...",
                            response.status_code,
                            attempt + 1,
                            max_attempts,
                            wait_time,
                        )
                        time.sleep(wait_time)
                        continue
                self._last_error = f"OpenAI Responses API error {response.status_code}: {error_msg}"
                logger.error(self._last_error)
                return ""

            try:
                data = response.json() or {}
            except Exception as exc:
                self._last_error = f"OpenAI Responses API returned invalid JSON: {exc}"
                logger.error(self._last_error)
                return ""

            output = self._extract_responses_output(data)
            if output:
                self._last_error = None
                return output

            self._last_error = "OpenAI Responses API returned no output text"
            logger.error(self._last_error)
            return ""

        return ""

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
        if not isinstance(content, str) or not content:
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

    @staticmethod
    def _prepend_paid_system_prompt(
        messages: List[dict],
        extra_system_prompt: Optional[str],
        *,
        is_gpt5: bool,
    ) -> List[dict]:
        prompt = str(extra_system_prompt or "").strip()
        if not is_gpt5 or not prompt:
            return messages
        return [{"role": "system", "content": prompt}] + list(messages)

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

        api_key = kwargs.get("api_key") or self.settings.ai_report_api_key
        base_url = kwargs.get("base_url") or self.settings.ai_report_base_url

        if not api_key:
            self._last_error = "AI_REPORT_API_KEY is not set"
            return ""

        model = kwargs.get("model") or self.settings.ai_report_model
        service_tier = kwargs.get("service_tier")
        response_format = kwargs.get("response_format")
        reasoning_effort = kwargs.get("reasoning_effort")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        is_gpt5 = self._is_gpt5_model(model)
        extra_paid_system_prompt = kwargs.get("paid_system_prompt")

        # OpenAI 유료 모델용 시스템 프롬프트 자동 분리 + GPT-5 보조 지침 선행 주입
        messages = self._convert_to_system_prompt(messages)
        messages = self._prepend_paid_system_prompt(
            messages,
            extra_paid_system_prompt,
            is_gpt5=is_gpt5,
        )

        max_attempts = 5 if service_tier == "flex" else 1
        current_tier = service_tier
        last_exception: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                url = f"{base_url.rstrip('/')}/chat/completions"
                payload = self._build_chat_payload(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=stop,
                    seed=seed,
                    top_p=top_p,
                    response_format=response_format,
                    current_tier=current_tier,
                    is_gpt5=is_gpt5,
                )
                response = self._post(url, payload=payload, headers=headers)

                if response.status_code >= 400:
                    error_msg = self._safe_error_message(response)

                    if "is not available for this model" in error_msg and current_tier == "flex":
                        logger.warning("Flex tier not available for %s. Falling back to standard.", model)
                        current_tier = None
                        continue

                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < max_attempts - 1:
                            wait_time = (2 ** attempt) + random.random()
                            logger.warning(
                                "OpenAI API error %s (attempt %s/%s). Retrying in %.2fs...",
                                response.status_code,
                                attempt + 1,
                                max_attempts,
                                wait_time,
                            )
                            time.sleep(wait_time)
                            continue

                    if self._should_try_responses(response.status_code, error_msg, is_gpt5=is_gpt5):
                        out = self._try_responses_api(
                            base_url=base_url,
                            headers=headers,
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            stop=stop,
                            seed=seed,
                            current_tier=current_tier,
                            response_format=response_format,
                            is_gpt5=is_gpt5,
                            reasoning_effort=reasoning_effort,
                        )
                        if out:
                            return out
                        return ""

                    self._last_error = f"OpenAI Chat Completions API error {response.status_code}: {error_msg}"
                    logger.error(self._last_error)
                    return ""

                data = response.json() or {}
                content = self._extract_chat_output(data)
                if content:
                    actual_tier = data.get("service_tier", "standard")
                    logger.info(
                        "OpenAI API Success. Model: %s, Requested Tier: %s, Actual Tier: %s",
                        model,
                        current_tier,
                        actual_tier,
                    )
                    self._last_error = None
                    return content

                logger.warning(
                    "OpenAI Chat Completions returned empty content for model=%s. Trying /responses fallback.",
                    model,
                )
                out = self._try_responses_api(
                    base_url=base_url,
                    headers=headers,
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=stop,
                    seed=seed,
                    current_tier=current_tier,
                    response_format=response_format,
                    is_gpt5=is_gpt5,
                    reasoning_effort=reasoning_effort,
                )
                if out:
                    return out
                self._last_error = self._last_error or "OpenAI Chat Completions returned empty content"
                return ""

            except Exception as e:
                last_exception = e
                if attempt < max_attempts - 1:
                    continue

        if last_exception is not None:
            logger.debug("Chat completions totally failed, trying responses fallback: %s", last_exception)
            out = self._try_responses_api(
                base_url=base_url,
                headers=headers,
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop,
                seed=seed,
                current_tier=current_tier,
                response_format=response_format,
                is_gpt5=is_gpt5,
                reasoning_effort=reasoning_effort,
            )
            if out:
                return out
            self._last_error = self._last_error or f"Paid LLM total failure: {last_exception}"
            logger.error(self._last_error)

        return ""

    def is_loaded(self) -> bool:
        return bool(self.settings.ai_report_api_key)

    def reset(self) -> None:
        pass
