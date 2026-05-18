from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

import requests

from ...core.config import settings
from ...core.schemas import ComfyUIImageGenerationRequest
from .constants import DEFAULT_CFG, DEFAULT_NEGATIVE_PROMPT, DEFAULT_STEPS, LOCAL_IMAGE_PLANNER_RETRIES
from .errors import ImageGenerationError
from .types import ToolSpec


logger = logging.getLogger(__name__)


def _llm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    return headers


def _openrouter_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.open_api_key:
        headers["Authorization"] = f"Bearer {settings.open_api_key}"
    return headers


def _llm_base_url_candidates() -> list[str]:
    candidates: list[str] = []
    configured = str(settings.llm_base_url or "").strip().rstrip("/")
    raw_candidates = [
        configured if ":8084" in configured else None,
        "http://llama-server-sycl-huihui:8084",
        "http://127.0.0.1:8084",
        "http://localhost:8084",
        configured if ":8084" not in configured else None,
    ]
    for candidate in raw_candidates:
        value = str(candidate or "").strip().rstrip("/")
        if value and value not in candidates:
            candidates.append(value)
    if not candidates:
        raise ImageGenerationError("LLM_BASE_URL is not configured")
    return candidates


def _tool_spec_from_arguments(arguments: dict[str, Any], request: ComfyUIImageGenerationRequest) -> ToolSpec:
    tool_prompt = str(arguments.get("prompt") or "").strip()
    if not tool_prompt:
        raise ImageGenerationError("AI planner did not include a prompt")

    negative_prompt = str(arguments.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT).strip() or DEFAULT_NEGATIVE_PROMPT
    width = int(arguments.get("width") or request.width)
    height = int(arguments.get("height") or request.height)
    steps = int(arguments.get("steps") or request.steps or DEFAULT_STEPS)
    cfg = float(arguments.get("cfg") or DEFAULT_CFG)
    seed = int(arguments.get("seed") or request.seed or random.randint(1, 2_147_483_647))

    width = min(max(width, 256), 1536)
    height = min(max(height, 256), 1536)
    steps = min(max(steps, 8), 60)
    cfg = min(max(cfg, 1.0), 12.0)

    return ToolSpec(
        prompt=tool_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
    )


def _parse_json_object_from_content(content: Any) -> dict[str, Any] | None:
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        return None

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    return data if isinstance(data, dict) else None


def _extract_content_arguments(message: dict[str, Any]) -> dict[str, Any] | None:
    data = _parse_json_object_from_content(message.get("content"))
    if not data:
        return None
    if isinstance(data.get("arguments"), dict):
        return data["arguments"]
    function = data.get("function")
    if isinstance(function, dict) and isinstance(function.get("arguments"), dict):
        return function["arguments"]
    if "prompt" in data:
        return data
    return None


def _extract_tool_spec(data: dict[str, Any], request: ComfyUIImageGenerationRequest) -> tuple[str, ToolSpec]:
    choices = data.get("choices") or []
    if not choices:
        raise ImageGenerationError("AI planner did not return any choices")

    message = (choices[0] or {}).get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        arguments = _extract_content_arguments(message)
        if arguments is not None:
            return "generate_comfyui_image", _tool_spec_from_arguments(arguments, request)
        raise ImageGenerationError("AI planner did not produce a ComfyUI tool call")

    tool_call = tool_calls[0] or {}
    function = tool_call.get("function") or {}
    tool_name = str(function.get("name") or "").strip()
    if tool_name != "generate_comfyui_image":
        raise ImageGenerationError(f"Unexpected tool call: {tool_name or 'unknown'}")

    raw_arguments = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ImageGenerationError(f"Invalid tool arguments from AI planner: {exc}") from exc

    return tool_name, _tool_spec_from_arguments(arguments, request)


def _build_image_planner_payload(
    request: ComfyUIImageGenerationRequest,
    *,
    model: str,
    prefer_json_content: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an image generation planner. "
                    "Always call the generate_comfyui_image tool for image requests. "
                    "Rewrite the user's request into a vivid English prompt suitable for image generation. "
                    "Keep the user's requested width and height when provided."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User request: {request.request}\n"
                    f"Preferred width: {request.width}\n"
                    f"Preferred height: {request.height}\n"
                    f"Preferred steps: {request.steps or DEFAULT_STEPS}"
                ),
            },
        ],
        "max_tokens": 384,
        "temperature": 0.2,
    }
    if prefer_json_content:
        payload["messages"] = [
            {
                "role": "system",
                "content": (
                    "You are an image generation planner. Return JSON only with keys: "
                    "prompt, negative_prompt, width, height, steps, cfg, seed. "
                    "Write a vivid English prompt suitable for ComfyUI image generation."
                ),
            },
            payload["messages"][1],
        ]
        payload["response_format"] = {"type": "json_object"}
        return payload

    payload["tools"] = [
        {
            "type": "function",
            "function": {
                "name": "generate_comfyui_image",
                "description": "Generate an image with ComfyUI from a text prompt.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {"type": "string"},
                        "negative_prompt": {"type": "string"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                        "steps": {"type": "integer"},
                        "cfg": {"type": "number"},
                        "seed": {"type": "integer"},
                    },
                    "required": ["prompt"],
                },
            },
        }
    ]
    payload["tool_choice"] = "auto"
    return payload


def _plan_image_generation_via_openrouter(
    request: ComfyUIImageGenerationRequest,
    *,
    previous_error: Exception | None = None,
) -> tuple[str, str, ToolSpec]:
    if not settings.open_api_key:
        if previous_error is not None:
            raise previous_error
        raise ImageGenerationError("OpenRouter API key is not configured")

    base_url = str(settings.image_generation_openrouter_base_url or "").strip().rstrip("/")
    model = str(settings.image_generation_openrouter_model or "google/gemma-4-31b-it").strip()
    if not base_url or not model:
        if previous_error is not None:
            raise previous_error
        raise ImageGenerationError("OpenRouter image generation fallback is not configured")

    last_exc: Exception | None = None
    for prefer_json_content in (False, True):
        payload = _build_image_planner_payload(request, model=model, prefer_json_content=prefer_json_content)
        try:
            response = requests.post(
                f"{base_url}/chat/completions",
                headers=_openrouter_headers(),
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            tool_name, tool_spec = _extract_tool_spec(response.json() or {}, request)
            return model, tool_name, tool_spec
        except (requests.RequestException, ImageGenerationError) as exc:
            last_exc = exc
            logger.warning("OpenRouter image planning failed via %s: %s", model, exc)

    if last_exc is not None:
        raise last_exc
    raise ImageGenerationError("OpenRouter image planning failed")


def plan_image_generation(request: ComfyUIImageGenerationRequest) -> tuple[str, str, ToolSpec]:
    last_exc: Exception | None = None

    for base_url in _llm_base_url_candidates():
        llm_model = settings.llm_remote_default_model or "local-model"
        try:
            response = requests.get(f"{base_url}/v1/models", headers=_llm_headers(), timeout=15)
            response.raise_for_status()
            models_data = response.json() or {}
            discovered_models = models_data.get("data") or models_data.get("models") or []
            if discovered_models and isinstance(discovered_models[0], dict):
                llm_model = str(discovered_models[0].get("id") or discovered_models[0].get("name") or llm_model)
        except requests.RequestException:
            logger.warning("Failed to auto-discover AI model id from %s; falling back to configured default.", base_url)

        for attempt in range(LOCAL_IMAGE_PLANNER_RETRIES + 1):
            payload = _build_image_planner_payload(request, model=llm_model)
            try:
                response = requests.post(
                    f"{base_url}/v1/chat/completions",
                    headers=_llm_headers(),
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json() or {}
                tool_name, tool_spec = _extract_tool_spec(data, request)
                resolved_model = str(data.get("model") or llm_model)
                return resolved_model, tool_name, tool_spec
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Local image planning request failed via %s: %s", base_url, exc)
                break
            except ImageGenerationError as exc:
                last_exc = exc
                logger.warning(
                    "Local image planning request failed via %s attempt=%d/%d: %s",
                    base_url,
                    attempt + 1,
                    LOCAL_IMAGE_PLANNER_RETRIES + 1,
                    exc,
                )
                continue

    return _plan_image_generation_via_openrouter(request, previous_error=last_exc)
