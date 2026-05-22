from __future__ import annotations

import base64
import mimetypes
import time
from typing import Any

import requests

from ...core.config import settings
from .constants import (
    ANIMA_HIGHRES_AESTHETIC_LORA_NAME,
    ANIMA_HIGHRES_AESTHETIC_LORA_STRENGTH,
    ANIMA_TURBO_LORA_NAME,
    ANIMA_TURBO_LORA_STRENGTH,
    DEFAULT_4K_FILENAME_PREFIX,
    DEFAULT_CLIENT_ID,
    DEFAULT_CLIP_NAME,
    DEFAULT_FILENAME_PREFIX,
    DEFAULT_IMG2IMG_FILENAME_PREFIX,
    DEFAULT_SAMPLER,
    DEFAULT_SCHEDULER,
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_UNET_NAME,
    DEFAULT_UPSCALE_MODEL_NAME,
    DEFAULT_VAE_NAME,
    REALISTIC_4K_FILENAME_PREFIX,
    REALISTIC_FILENAME_PREFIX,
)
from .errors import ImageGenerationError
from .types import ToolSpec


def _comfyui_url(path: str) -> str:
    return f"{settings.comfyui_base_url.rstrip('/')}{path}"


def build_workflow(
    tool_spec: ToolSpec,
    *,
    model_type: str = "anime",
    output_width: int | None = None,
    output_height: int | None = None,
    upscale_model: str | None = None,
) -> dict[str, Any]:
    if model_type == "realistic":
        return build_z_image_turbo_workflow(
            tool_spec,
            output_width=output_width,
            output_height=output_height,
            upscale_model=upscale_model,
        )

    save_image_input: list[Any] = ["8", 0]
    filename_prefix = DEFAULT_FILENAME_PREFIX
    workflow: dict[str, Any] = {
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
            "inputs": {"clip": ["14", 1], "text": tool_spec.prompt},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["14", 1], "text": tool_spec.negative_prompt},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["14", 0],
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
            "inputs": {"images": save_image_input, "filename_prefix": filename_prefix},
        },
        "13": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["2", 0],
                "lora_name": ANIMA_TURBO_LORA_NAME,
                "strength_model": ANIMA_TURBO_LORA_STRENGTH,
                "strength_clip": ANIMA_TURBO_LORA_STRENGTH,
            },
        },
        "14": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["13", 0],
                "clip": ["13", 1],
                "lora_name": ANIMA_HIGHRES_AESTHETIC_LORA_NAME,
                "strength_model": ANIMA_HIGHRES_AESTHETIC_LORA_STRENGTH,
                "strength_clip": ANIMA_HIGHRES_AESTHETIC_LORA_STRENGTH,
            },
        },
    }
    if output_width is not None and output_height is not None:
        workflow["10"] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": upscale_model or DEFAULT_UPSCALE_MODEL_NAME},
        }
        workflow["11"] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["10", 0], "image": ["8", 0]},
        }
        workflow["12"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["11", 0],
                "upscale_method": "lanczos",
                "width": output_width,
                "height": output_height,
                "crop": "disabled",
            },
        }
        workflow["9"]["inputs"] = {
            "images": ["12", 0],
            "filename_prefix": DEFAULT_4K_FILENAME_PREFIX,
        }
    return workflow


def build_image_to_image_workflow(
    tool_spec: ToolSpec,
    *,
    input_name: str,
    denoise: float,
    model_type: str = "anime",
) -> dict[str, Any]:
    if model_type == "realistic":
        return build_z_image_turbo_image_to_image_workflow(
            tool_spec,
            input_name=input_name,
            denoise=denoise,
        )

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
            "class_type": "LoadImage",
            "inputs": {"image": input_name},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["14", 1], "text": tool_spec.prompt},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["14", 1], "text": tool_spec.negative_prompt},
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["14", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["16", 0],
                "seed": tool_spec.seed,
                "steps": tool_spec.steps,
                "cfg": tool_spec.cfg,
                "sampler_name": DEFAULT_SAMPLER,
                "scheduler": DEFAULT_SCHEDULER,
                "denoise": denoise,
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": DEFAULT_IMG2IMG_FILENAME_PREFIX},
        },
        "13": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["1", 0],
                "clip": ["2", 0],
                "lora_name": ANIMA_TURBO_LORA_NAME,
                "strength_model": ANIMA_TURBO_LORA_STRENGTH,
                "strength_clip": ANIMA_TURBO_LORA_STRENGTH,
            },
        },
        "14": {
            "class_type": "LoraLoader",
            "inputs": {
                "model": ["13", 0],
                "clip": ["13", 1],
                "lora_name": ANIMA_HIGHRES_AESTHETIC_LORA_NAME,
                "strength_model": ANIMA_HIGHRES_AESTHETIC_LORA_STRENGTH,
                "strength_clip": ANIMA_HIGHRES_AESTHETIC_LORA_STRENGTH,
            },
        },
        "15": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["4", 0],
                "upscale_method": "lanczos",
                "width": tool_spec.width,
                "height": tool_spec.height,
                "crop": "disabled",
            },
        },
        "16": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["15", 0], "vae": ["3", 0]},
        },
    }


def build_z_image_turbo_image_to_image_workflow(
    tool_spec: ToolSpec,
    *,
    input_name: str,
    denoise: float,
) -> dict[str, Any]:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": settings.comfyui_z_image_unet_name, "weight_dtype": "fp8_e4m3fn"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": settings.comfyui_z_image_clip_name, "type": "lumina2", "device": "default"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": settings.comfyui_z_image_vae_name},
        },
        "4": {
            "class_type": "LoadImage",
            "inputs": {"image": input_name},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": tool_spec.prompt},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": ""},
        },
        "7": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["1", 0], "shift": 3.1},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["7", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["12", 0],
                "seed": tool_spec.seed,
                "steps": tool_spec.steps,
                "cfg": tool_spec.cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": denoise,
            },
        },
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["3", 0]},
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {"images": ["9", 0], "filename_prefix": REALISTIC_FILENAME_PREFIX},
        },
        "11": {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["4", 0],
                "upscale_method": "lanczos",
                "width": tool_spec.width,
                "height": tool_spec.height,
                "crop": "disabled",
            },
        },
        "12": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["11", 0], "vae": ["3", 0]},
        },
    }


def build_z_image_turbo_workflow(
    tool_spec: ToolSpec,
    *,
    output_width: int | None = None,
    output_height: int | None = None,
    upscale_model: str | None = None,
) -> dict[str, Any]:
    workflow: dict[str, Any] = {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": settings.comfyui_z_image_unet_name, "weight_dtype": "fp8_e4m3fn"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": settings.comfyui_z_image_clip_name, "type": "lumina2", "device": "default"},
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": settings.comfyui_z_image_vae_name},
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
            "inputs": {"clip": ["2", 0], "text": ""},
        },
        "7": {
            "class_type": "ModelSamplingAuraFlow",
            "inputs": {"model": ["1", 0], "shift": 3.1},
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["7", 0],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "latent_image": ["4", 0],
                "seed": tool_spec.seed,
                "steps": tool_spec.steps,
                "cfg": tool_spec.cfg,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["3", 0]},
        },
        "10": {
            "class_type": "SaveImage",
            "inputs": {"images": ["9", 0], "filename_prefix": REALISTIC_FILENAME_PREFIX},
        },
    }
    if output_width is not None and output_height is not None:
        workflow["11"] = {
            "class_type": "UpscaleModelLoader",
            "inputs": {"model_name": upscale_model or DEFAULT_UPSCALE_MODEL_NAME},
        }
        workflow["12"] = {
            "class_type": "ImageUpscaleWithModel",
            "inputs": {"upscale_model": ["11", 0], "image": ["9", 0]},
        }
        workflow["13"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["12", 0],
                "upscale_method": "lanczos",
                "width": output_width,
                "height": output_height,
                "crop": "disabled",
            },
        }
        workflow["10"]["inputs"] = {
            "images": ["13", 0],
            "filename_prefix": REALISTIC_4K_FILENAME_PREFIX,
        }
    return workflow


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
