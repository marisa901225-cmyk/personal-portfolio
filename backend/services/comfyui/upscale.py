from __future__ import annotations

import base64
import logging
import re
import uuid
from io import BytesIO

import requests
from PIL import Image

from ...core.schemas import AnimeImageUpscaleRequest, AnimeImageUpscaleResponse
from .constants import DEFAULT_UPSCALE_MODEL_NAME, MAX_UPSCALE_SOURCE_BYTES
from .errors import ImageUpscaleError
from .workflow import _comfyui_url, extract_image_entry, fetch_image_data_url, submit_prompt, wait_for_completion


logger = logging.getLogger(__name__)

MODEL_ALIASES = {
    "realesrgan-x4plus-anime": DEFAULT_UPSCALE_MODEL_NAME,
    "realesr-animevideov3": DEFAULT_UPSCALE_MODEL_NAME,
    DEFAULT_UPSCALE_MODEL_NAME: DEFAULT_UPSCALE_MODEL_NAME,
}


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


def _upload_comfyui_input(image_bytes: bytes, extension: str) -> str:
    filename = f"anime_upscale_source_{uuid.uuid4().hex}.{extension}"
    content_type = "image/jpeg" if extension == "jpg" else f"image/{extension}"
    response = requests.post(
        _comfyui_url("/upload/image"),
        data={"type": "input", "overwrite": "true"},
        files={"image": (filename, image_bytes, content_type)},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json() or {}
    return str(data.get("name") or filename)


def _build_upscale_workflow(
    *,
    input_name: str,
    model_name: str,
    target_width: int | None,
    target_height: int | None,
) -> dict[str, dict]:
    save_input = ["3", 0]
    workflow = {
        "1": {"class_type": "LoadImage", "inputs": {"image": input_name}},
        "2": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model_name}},
        "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]}},
        "5": {"class_type": "SaveImage", "inputs": {"images": save_input, "filename_prefix": "anime_upscaled"}},
    }
    if target_width is not None and target_height is not None:
        workflow["4"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["3", 0],
                "upscale_method": "lanczos",
                "width": target_width,
                "height": target_height,
                "crop": "disabled",
            },
        }
        workflow["5"]["inputs"]["images"] = ["4", 0]
    return workflow


def _image_size_from_data_url(image_data_url: str) -> tuple[int, int]:
    encoded = image_data_url.split(",", 1)[1]
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        return image.width, image.height


def _convert_output_format(image_data_url: str, output_format: str) -> str:
    if output_format == "png":
        return image_data_url

    encoded = image_data_url.split(",", 1)[1]
    with Image.open(BytesIO(base64.b64decode(encoded))) as image:
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        output = BytesIO()
        image.save(output, format="JPEG", quality=95)
    return f"data:image/jpeg;base64,{base64.b64encode(output.getvalue()).decode('ascii')}"


def upscale_anime_image(request: AnimeImageUpscaleRequest) -> AnimeImageUpscaleResponse:
    model_name = MODEL_ALIASES.get(request.model)
    if model_name is None:
        raise ImageUpscaleError(f"Unsupported anime upscale model: {request.model}")
    if request.target_width is None and request.target_height is not None:
        raise ImageUpscaleError("target_width and target_height must be provided together")
    if request.target_width is not None and request.target_height is None:
        raise ImageUpscaleError("target_width and target_height must be provided together")

    image_bytes, source_ext = _decode_image_data_url(request.image_data_url)

    try:
        input_name = _upload_comfyui_input(image_bytes, source_ext)
        workflow = _build_upscale_workflow(
            input_name=input_name,
            model_name=model_name,
            target_width=request.target_width,
            target_height=request.target_height,
        )
        prompt_id = submit_prompt(workflow)
        history = wait_for_completion(prompt_id, timeout_sec=180)
        image_entry = extract_image_entry(history)
        image_data_url = fetch_image_data_url(image_entry)
    except requests.HTTPError as exc:
        body = exc.response.text[:500] if exc.response is not None else ""
        raise ImageUpscaleError(f"ComfyUI anime upscaling request failed: {exc}. {body}".strip()) from exc
    except requests.RequestException as exc:
        raise ImageUpscaleError(f"Failed to reach ComfyUI for anime upscaling: {exc}") from exc

    image_data_url = _convert_output_format(image_data_url, request.output_format)
    output_width, output_height = _image_size_from_data_url(image_data_url)
    filename_ext = "jpg" if request.output_format == "jpg" else "png"

    return AnimeImageUpscaleResponse(
        model=model_name,
        scale=request.scale,
        width=output_width,
        height=output_height,
        filename=f"anime_upscaled_x{request.scale}.{filename_ext}",
        image_data_url=image_data_url,
    )
