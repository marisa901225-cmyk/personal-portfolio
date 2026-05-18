from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import httpx
from PIL import Image

from ...core.config import settings
from ...core.schemas import AnimeImageUpscaleRequest, AnimeImageUpscaleResponse
from .constants import MAX_UPSCALE_SOURCE_BYTES
from .errors import ImageUpscaleError
from .vram import comfyui_vram_guard


logger = logging.getLogger(__name__)


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


def _prepare_upscale_output(path: Path, request: AnimeImageUpscaleRequest) -> tuple[Path, int, int]:
    target_width = request.target_width
    target_height = request.target_height
    if target_width is None and target_height is None:
        with Image.open(path) as image:
            return path, image.width, image.height

    if target_width is None or target_height is None:
        raise ImageUpscaleError("target_width and target_height must be provided together")

    resized_path = path.with_name(f"resized.{request.output_format}")
    with Image.open(path) as image:
        resized = image.resize((target_width, target_height), Image.Resampling.LANCZOS)
        if request.output_format == "jpg" and resized.mode not in {"RGB", "L"}:
            resized = resized.convert("RGB")
        resized.save(resized_path, format="JPEG" if request.output_format == "jpg" else "PNG")
    return resized_path, target_width, target_height


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
            with comfyui_vram_guard():
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
        except httpx.HTTPError as exc:
            raise ImageUpscaleError(f"Failed to control ComfyUI container for VRAM: {exc}") from exc

        if not output_path.is_file():
            stdout = (completed.stdout or "").strip()[-500:]
            raise ImageUpscaleError(f"Anime upscaling completed without an output file: {stdout}")

        final_path, output_width, output_height = _prepare_upscale_output(output_path, request)
        image_data_url = _read_image_data_url(final_path, request.output_format)

    return AnimeImageUpscaleResponse(
        model=request.model,
        scale=request.scale,
        width=output_width,
        height=output_height,
        filename=f"anime_upscaled_x{request.scale}.{request.output_format}",
        image_data_url=image_data_url,
    )
