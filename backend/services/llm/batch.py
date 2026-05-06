from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any, Iterable

try:
    import httpx  # type: ignore
except Exception:  # pragma: no cover
    httpx = None

from .config import Settings


@dataclass(frozen=True)
class LLMBatchRequest:
    key: str
    messages: list[dict[str, Any]]
    max_tokens: int = 4096
    temperature: float = 0.2


@dataclass(frozen=True)
class LLMBatchJob:
    provider: str
    id: str
    status: str | None = None
    raw: dict[str, Any] | None = None


class OpenAIBatchClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._client = httpx.Client(timeout=self.settings.ai_report_timeout_sec) if httpx else None

    def submit_responses_batch(
        self,
        requests: Iterable[LLMBatchRequest],
        *,
        model: str | None = None,
        display_name: str = "translation-batch",
        metadata: dict[str, str] | None = None,
    ) -> LLMBatchJob:
        api_key = self.settings.ai_report_api_key
        if not api_key:
            raise ValueError("AI_REPORT_API_KEY is not set")

        selected_model = model or self.settings.translation_batch_model or self.settings.ai_report_model
        jsonl = self._build_responses_jsonl(requests, model=selected_model)
        headers = {"Authorization": f"Bearer {api_key}"}
        upload = self._post(
            f"{self.settings.ai_report_base_url.rstrip('/')}/files",
            headers=headers,
            data={"purpose": "batch"},
            files={"file": ("translation-batch.jsonl", io.BytesIO(jsonl.encode("utf-8")), "application/jsonl")},
        ).json()
        input_file_id = str(upload.get("id") or "").strip()
        if not input_file_id:
            raise RuntimeError(f"OpenAI batch input upload did not return file id: {upload}")

        create_headers = {**headers, "Content-Type": "application/json"}
        payload = {
            "input_file_id": input_file_id,
            "endpoint": "/v1/responses",
            "completion_window": "24h",
            "metadata": {"display_name": display_name, **(metadata or {})},
        }
        created = self._post(
            f"{self.settings.ai_report_base_url.rstrip('/')}/batches",
            headers=create_headers,
            json=payload,
        ).json()
        return LLMBatchJob(
            provider="openai",
            id=str(created.get("id") or ""),
            status=created.get("status"),
            raw=created,
        )

    def retrieve_batch(self, batch_id: str) -> LLMBatchJob:
        api_key = self.settings.ai_report_api_key
        if not api_key:
            raise ValueError("AI_REPORT_API_KEY is not set")
        data = self._get(
            f"{self.settings.ai_report_base_url.rstrip('/')}/batches/{batch_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        ).json()
        return LLMBatchJob(provider="openai", id=str(data.get("id") or batch_id), status=data.get("status"), raw=data)

    def download_output_text(self, file_id: str) -> str:
        api_key = self.settings.ai_report_api_key
        if not api_key:
            raise ValueError("AI_REPORT_API_KEY is not set")
        response = self._get(
            f"{self.settings.ai_report_base_url.rstrip('/')}/files/{file_id}/content",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        return getattr(response, "text", "")

    @staticmethod
    def parse_responses_jsonl(text: str) -> dict[str, str]:
        outputs: dict[str, str] = {}
        for line in text.splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = str(row.get("custom_id") or "").strip()
            body = (((row.get("response") or {}).get("body")) or {})
            output = _extract_openai_output_text(body)
            if key:
                outputs[key] = output
        return outputs

    def _post(self, url: str, **kwargs: Any):
        if self._client is None:
            raise RuntimeError("httpx is not installed")
        response = self._client.post(url, **kwargs)
        response.raise_for_status()
        return response

    def _get(self, url: str, **kwargs: Any):
        if self._client is None:
            raise RuntimeError("httpx is not installed")
        response = self._client.get(url, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _build_responses_jsonl(requests: Iterable[LLMBatchRequest], *, model: str) -> str:
        lines: list[str] = []
        for request in requests:
            body = {
                "model": model,
                "input": _normalize_openai_messages(request.messages),
                "max_output_tokens": max(int(request.max_tokens), 16),
                "temperature": request.temperature,
            }
            lines.append(
                json.dumps(
                    {
                        "custom_id": request.key,
                        "method": "POST",
                        "url": "/v1/responses",
                        "body": body,
                    },
                    ensure_ascii=False,
                )
            )
        return "\n".join(lines) + ("\n" if lines else "")


class GeminiBatchClient:
    INLINE_LIMIT_BYTES = 20 * 1024 * 1024

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._client = httpx.Client(timeout=self.settings.ai_report_timeout_sec) if httpx else None

    def submit_generate_content_batch(
        self,
        requests: Iterable[LLMBatchRequest],
        *,
        model: str | None = None,
        display_name: str = "translation-batch",
    ) -> LLMBatchJob:
        api_key = self.settings.google_token
        if not api_key:
            raise ValueError("GOOGLE_TOKEN is not set")

        selected_model = (model or self.settings.translation_batch_model or "gemini-2.5-flash").removeprefix("models/")
        payload = {
            "batch": {
                "display_name": display_name,
                "input_config": {
                    "requests": {
                        "requests": [
                            {
                                "request": _messages_to_gemini_request(request),
                                "metadata": {"key": request.key},
                            }
                            for request in requests
                        ]
                    }
                },
            }
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(encoded) > self.INLINE_LIMIT_BYTES:
            raise ValueError("Gemini inline batch payload exceeds 20MB; split the batch or use file input")

        data = self._post(
            f"{self.settings.gemini_batch_base_url.rstrip('/')}/models/{selected_model}:batchGenerateContent",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        ).json()
        return LLMBatchJob(
            provider="gemini",
            id=str(data.get("name") or data.get("batch", {}).get("name") or ""),
            status=(data.get("metadata") or {}).get("state") or data.get("state"),
            raw=data,
        )

    def retrieve_batch(self, batch_name: str) -> LLMBatchJob:
        api_key = self.settings.google_token
        if not api_key:
            raise ValueError("GOOGLE_TOKEN is not set")
        normalized = batch_name.lstrip("/")
        data = self._get(
            f"{self.settings.gemini_batch_base_url.rstrip('/')}/{normalized}",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        ).json()
        return LLMBatchJob(
            provider="gemini",
            id=str(data.get("name") or batch_name),
            status=(data.get("metadata") or {}).get("state") or data.get("state"),
            raw=data,
        )

    @staticmethod
    def parse_inline_responses(batch_payload: dict[str, Any]) -> dict[str, str]:
        responses = (((batch_payload.get("dest") or {}).get("inlined_responses")) or [])
        outputs: dict[str, str] = {}
        for idx, item in enumerate(responses):
            key = str((item.get("metadata") or {}).get("key") or f"request-{idx}").strip()
            outputs[key] = _extract_gemini_text(item.get("response") or {})
        return outputs

    def _post(self, url: str, **kwargs: Any):
        if self._client is None:
            raise RuntimeError("httpx is not installed")
        response = self._client.post(url, **kwargs)
        response.raise_for_status()
        return response

    def _get(self, url: str, **kwargs: Any):
        if self._client is None:
            raise RuntimeError("httpx is not installed")
        response = self._client.get(url, **kwargs)
        response.raise_for_status()
        return response


def _normalize_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"role": str(message.get("role") or "user"), "content": str(message.get("content") or "")}
        for message in messages
    ]


def _messages_to_gemini_request(request: LLMBatchRequest) -> dict[str, Any]:
    system_parts: list[dict[str, str]] = []
    contents: list[dict[str, Any]] = []
    for message in request.messages:
        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")
        if role == "system":
            system_parts.append({"text": text})
            continue
        contents.append(
            {
                "role": "model" if role == "assistant" else "user",
                "parts": [{"text": text}],
            }
        )

    payload: dict[str, Any] = {
        "contents": contents,
        "generation_config": {
            "temperature": request.temperature,
            "max_output_tokens": max(int(request.max_tokens), 16),
        },
    }
    if system_parts:
        payload["system_instruction"] = {"parts": system_parts}
    return payload


def _extract_openai_output_text(body: dict[str, Any]) -> str:
    direct = body.get("output_text")
    if isinstance(direct, str):
        return direct

    chunks: list[str] = []
    for item in body.get("output") or []:
        for content in item.get("content") or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for candidate in payload.get("candidates") or []:
        for part in ((candidate.get("content") or {}).get("parts")) or []:
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)
