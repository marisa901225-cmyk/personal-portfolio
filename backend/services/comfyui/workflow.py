from __future__ import annotations

import base64
import mimetypes
import time
from typing import Any

import requests

from ...core.config import settings
from .constants import (
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIP_NAME,
    DEFAULT_FILENAME_PREFIX,
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_UNET_NAME,
    DEFAULT_VAE_NAME,
)
from .errors import ImageGenerationError
from .types import ToolSpec


def _comfyui_url(path: str) -> str:
    return f"{settings.comfyui_base_url.rstrip('/')}{path}"


def build_workflow(tool_spec: ToolSpec) -> dict[str, Any]:
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


def submit_prompt(workflow: dict[str, Any]) -> str:
    payload = {"prompt": workflow, "client_id": DEFAULT_CLIENT_ID}
    response = requests.post(_comfyui_url("/prompt"), json=payload, timeout=30)
    response.raise_for_status()
    data = response.json() or {}
    prompt_id = str(data.get("prompt_id") or "").strip()
    if not prompt_id:
        raise ImageGenerationError(f"ComfyUI did not return prompt_id: {data}")
    return prompt_id


def fetch_history(prompt_id: str) -> dict[str, Any] | None:
    response = requests.get(_comfyui_url(f"/history/{prompt_id}"), timeout=15)
    response.raise_for_status()
    data = response.json() or {}
    if isinstance(data, dict) and prompt_id in data:
        return data[prompt_id]
    if isinstance(data, dict) and data.get("status"):
        return data
    return None


def wait_for_completion(prompt_id: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    started = time.time()
    while time.time() - started < timeout_sec:
        history = fetch_history(prompt_id)
        if history:
            status = (history.get("status") or {})
            if status.get("completed"):
                return history
        time.sleep(1.5)
    raise ImageGenerationError(f"Timed out waiting for ComfyUI prompt {prompt_id}")


def extract_image_entry(history: dict[str, Any]) -> dict[str, str]:
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


def fetch_image_data_url(image_entry: dict[str, str]) -> str:
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
