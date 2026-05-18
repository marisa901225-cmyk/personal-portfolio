from __future__ import annotations

import base64
import json
import logging
import mimetypes
import random
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from ..core.config import settings
from ..core.schemas import (
    AnimeImageUpscaleRequest,
    AnimeImageUpscaleResponse,
    ComfyUIImageGenerationRequest,
    ComfyUIImageGenerationResponse,
)


logger = logging.getLogger(__name__)

DEFAULT_NEGATIVE_PROMPT = "low quality, blurry, distorted, bad anatomy, watermark, text, logo"
DEFAULT_STEPS = 20
DEFAULT_CFG = 4.0
DEFAULT_SAMPLER = "euler"
DEFAULT_SCHEDULER = "simple"
DEFAULT_UNET_NAME = "UltraReal_anima.safetensors"
DEFAULT_CLIP_NAME = "qwen_3_06b_base.safetensors"
DEFAULT_VAE_NAME = "qwen_image_vae.safetensors"
DEFAULT_FILENAME_PREFIX = "e4b_comfyui"
DEFAULT_CLIENT_ID = "myasset-e4b-comfyui"
DEFAULT_TIMEOUT_SEC = 180
MAX_UPSCALE_SOURCE_BYTES = 30 * 1024 * 1024


class ImageGenerationError(RuntimeError):
    """Raised when e4b tool execution or ComfyUI generation fails."""


class ImageUpscaleError(RuntimeError):
    """Raised when anime RealESRGAN upscaling fails."""


@dataclass(frozen=True)
class _ToolSpec:
    prompt: str
    negative_prompt: str
    width: int
    height: int
    steps: int
    cfg: float
    seed: int


def _llm_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"
    return headers


def _llm_chat_url() -> str:
    base_url = (settings.llm_base_url or "").strip().rstrip("/")
    if not base_url:
        raise ImageGenerationError("LLM_BASE_URL is not configured")
    return f"{base_url}/v1/chat/completions"


def _llm_models_url() -> str:
    base_url = (settings.llm_base_url or "").strip().rstrip("/")
    if not base_url:
        raise ImageGenerationError("LLM_BASE_URL is not configured")
    return f"{base_url}/v1/models"


def _comfyui_url(path: str) -> str:
    return f"{settings.comfyui_base_url.rstrip('/')}{path}"


def _llm_base_url_candidates() -> list[str]:
    candidates: list[str] = []
    raw_candidates = [
        settings.llm_base_url,
        "http://127.0.0.1:8084",
        "http://localhost:8084",
    ]
    for candidate in raw_candidates:
        value = str(candidate or "").strip().rstrip("/")
        if value and value not in candidates:
            candidates.append(value)
    if not candidates:
        raise ImageGenerationError("LLM_BASE_URL is not configured")
    return candidates


def _extract_tool_spec(data: dict[str, Any], request: ComfyUIImageGenerationRequest) -> tuple[str, _ToolSpec]:
    choices = data.get("choices") or []
    if not choices:
        raise ImageGenerationError("e4b did not return any choices")

    message = (choices[0] or {}).get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        raise ImageGenerationError("e4b did not produce a ComfyUI tool call")

    tool_call = tool_calls[0] or {}
    function = tool_call.get("function") or {}
    tool_name = str(function.get("name") or "").strip()
    if tool_name != "generate_comfyui_image":
        raise ImageGenerationError(f"Unexpected tool call: {tool_name or 'unknown'}")

    raw_arguments = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ImageGenerationError(f"Invalid tool arguments from e4b: {exc}") from exc

    tool_prompt = str(arguments.get("prompt") or "").strip()
    if not tool_prompt:
        raise ImageGenerationError("e4b tool call did not include a prompt")

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

    return tool_name, _ToolSpec(
        prompt=tool_prompt,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        steps=steps,
        cfg=cfg,
        seed=seed,
    )


def _plan_image_generation(request: ComfyUIImageGenerationRequest) -> tuple[str, str, _ToolSpec]:
    last_exc: requests.RequestException | None = None

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
            logger.warning("Failed to auto-discover e4b model id from %s; falling back to configured default.", base_url)

        payload = {
            "model": llm_model,
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
            "tools": [
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
            ],
            "tool_choice": "auto",
        }
        try:
            response = requests.post(f"{base_url}/v1/chat/completions", headers=_llm_headers(), json=payload, timeout=60)
            response.raise_for_status()
            data = response.json() or {}
            tool_name, tool_spec = _extract_tool_spec(data, request)
            resolved_model = str(data.get("model") or llm_model)
            return resolved_model, tool_name, tool_spec
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("e4b image planning request failed via %s: %s", base_url, exc)
            continue

    if last_exc is not None:
        raise last_exc

    payload = {
        "model": settings.llm_remote_default_model or "local-model",
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
        "tools": [
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
        ],
        "tool_choice": "auto",
    }
    raise ImageGenerationError(f"Failed to plan image generation: {payload}")


def _build_workflow(tool_spec: _ToolSpec) -> dict[str, Any]:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": DEFAULT_UNET_NAME, "weight_dtype": "default"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": DEFAULT_CLIP_NAME, "type": "qwen_image", "device": "default"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": DEFAULT_VAE_NAME},
        },
        "4": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": tool_spec.width, "height": tool_spec.height, "batch_size": 1},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": tool_spec.prompt},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": tool_spec.negative_prompt},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["4", 0],
                "seed": tool_spec.seed,
                "steps": tool_spec.steps,
                "cfg": tool_spec.cfg,
                "sampler_name": DEFAULT_SAMPLER,
                "scheduler": DEFAULT_SCHEDULER,
                "denoise": 1.0,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": DEFAULT_FILENAME_PREFIX},
        },
    }


def _submit_prompt(workflow: dict[str, Any]) -> str:
    payload = {"prompt": workflow, "client_id": DEFAULT_CLIENT_ID}
    response = requests.post(_comfyui_url("/prompt"), json=payload, timeout=30)
    response.raise_for_status()
    data = response.json() or {}
    prompt_id = str(data.get("prompt_id") or "").strip()
    if not prompt_id:
        raise ImageGenerationError(f"ComfyUI did not return prompt_id: {data}")
    return prompt_id


def _fetch_history(prompt_id: str) -> dict[str, Any] | None:
    response = requests.get(_comfyui_url(f"/history/{prompt_id}"), timeout=15)
    response.raise_for_status()
    data = response.json() or {}
    if isinstance(data, dict) and prompt_id in data:
        return data[prompt_id]
    if isinstance(data, dict) and data.get("status"):
        return data
    return None


def _wait_for_completion(prompt_id: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    started = time.time()
    while time.time() - started < timeout_sec:
        history = _fetch_history(prompt_id)
        if history:
            status = (history.get("status") or {})
            if status.get("completed"):
                return history
        time.sleep(1.5)
    raise ImageGenerationError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def _extract_image_entry(history: dict[str, Any]) -> dict[str, str]:
    outputs = history.get("outputs") or {}
    for node_output in outputs.values():
        images = (node_output or {}).get("images") or []
        if images:
            entry = images[0] or {}
            filename = str(entry.get("filename") or "").strip()
            if filename:
                return {
                    "filename": filename,
                    "subfolder": str(entry.get("subfolder") or ""),
                    "type": str(entry.get("type") or "output"),
                }
    raise ImageGenerationError(f"ComfyUI completed without output images: {history}")


def _fetch_image_data_url(image_entry: dict[str, str]) -> str:
    params = {
        "filename": image_entry["filename"],
        "subfolder": image_entry["subfolder"],
        "type": image_entry["type"],
    }
    response = requests.get(_comfyui_url("/view"), params=params, timeout=60)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type") or mimetypes.guess_type(image_entry["filename"])[0] or "image/png"
    encoded = base64.b64encode(response.content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _load_anime_upscale_model_ids() -> set[str]:
    config_path = Path(settings.realesrgan_models_config_path)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError:
        logger.warning("Anime upscale model config not found: %s", config_path)
        return {"realesrgan-x4plus-anime", "realesr-animevideov3"}
    except json.JSONDecodeError as exc:
        raise ImageUpscaleError(f"Invalid anime upscale model config: {exc}") from exc

    model_ids = {
        str(item.get("id") or "").strip()
        for item in data.get("models", [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    if not model_ids:
        raise ImageUpscaleError("Anime upscale model config does not include any models")
    return model_ids


def _decode_image_data_url(image_data_url: str) -> tuple[bytes, str]:
    match = re.match(r"^data:(image/(png|jpeg|jpg|webp));base64,(.+)$", image_data_url, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ImageUpscaleError("image_data_url must be a base64 image data URL")

    extension = "jpg" if match.group(2).lower() in {"jpeg", "jpg"} else match.group(2).lower()
    try:
        image_bytes = base64.b64decode(match.group(3), validate=True)
    except ValueError as exc:
        raise ImageUpscaleError("image_data_url contains invalid base64 data") from exc

    if not image_bytes:
        raise ImageUpscaleError("image_data_url is empty")
    if len(image_bytes) > MAX_UPSCALE_SOURCE_BYTES:
        raise ImageUpscaleError("image_data_url is too large for anime upscaling")
    return image_bytes, extension


def _read_image_data_url(path: Path, output_format: str) -> str:
    content_type = "image/jpeg" if output_format == "jpg" else "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def upscale_anime_image(request: AnimeImageUpscaleRequest) -> AnimeImageUpscaleResponse:
    allowed_models = _load_anime_upscale_model_ids()
    if request.model not in allowed_models:
        raise ImageUpscaleError(f"Unsupported anime upscale model: {request.model}")

    bin_path = Path(settings.realesrgan_bin_path)
    model_dir = Path(settings.realesrgan_model_dir)
    model_prefix = model_dir / "models" / request.model
    if not bin_path.is_file():
        raise ImageUpscaleError(f"RealESRGAN binary not found: {bin_path}")
    if not (model_prefix.with_suffix(".bin").is_file() and model_prefix.with_suffix(".param").is_file()):
        raise ImageUpscaleError(f"RealESRGAN model files not found for: {request.model}")

    image_bytes, source_ext = _decode_image_data_url(request.image_data_url)

    with tempfile.TemporaryDirectory(prefix="anime-upscale-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / f"source.{source_ext}"
        output_path = tmp_path / f"upscaled.{request.output_format}"
        input_path.write_bytes(image_bytes)

        command = [
            str(bin_path),
            "-i",
            str(input_path),
            "-o",
            str(output_path),
            "-n",
            request.model,
            "-s",
            str(request.scale),
            "-f",
            request.output_format,
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(model_dir),
                check=True,
                capture_output=True,
                text=True,
                timeout=settings.realesrgan_timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            raise ImageUpscaleError("Anime upscaling timed out") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()[-1200:]
            raise ImageUpscaleError(f"Anime upscaling failed: {stderr}") from exc

        if not output_path.is_file():
            stdout = (completed.stdout or "").strip()[-500:]
            raise ImageUpscaleError(f"Anime upscaling completed without an output file: {stdout}")

        image_data_url = _read_image_data_url(output_path, request.output_format)

    return AnimeImageUpscaleResponse(
        model=request.model,
        scale=request.scale,
        filename=f"anime_upscaled_x{request.scale}.{request.output_format}",
        image_data_url=image_data_url,
    )


def generate_image_with_e4b(request: ComfyUIImageGenerationRequest) -> ComfyUIImageGenerationResponse:
    try:
        llm_model, tool_name, tool_spec = _plan_image_generation(request)
        workflow = _build_workflow(tool_spec)
        prompt_id = _submit_prompt(workflow)
        history = _wait_for_completion(prompt_id)
        image_entry = _extract_image_entry(history)
        image_data_url = _fetch_image_data_url(image_entry)
    except requests.HTTPError as exc:
        body = ""
        if exc.response is not None:
            try:
                body = exc.response.text[:500]
            except Exception:
                body = ""
        raise ImageGenerationError(f"Upstream image generation request failed: {exc}. {body}".strip()) from exc
    except requests.RequestException as exc:
        raise ImageGenerationError(f"Failed to reach e4b or ComfyUI: {exc}") from exc

    logger.info("Generated ComfyUI image via e4b tool call: prompt_id=%s file=%s", prompt_id, image_entry["filename"])
    return ComfyUIImageGenerationResponse(
        request=request.request,
        llm_model=llm_model,
        tool_name=tool_name,
        tool_prompt=tool_spec.prompt,
        negative_prompt=tool_spec.negative_prompt,
        width=tool_spec.width,
        height=tool_spec.height,
        steps=tool_spec.steps,
        cfg=tool_spec.cfg,
        seed=tool_spec.seed,
        prompt_id=prompt_id,
        filename=image_entry["filename"],
        subfolder=image_entry["subfolder"],
        image_data_url=image_data_url,
    )
