from __future__ import annotations

import base64
import logging
import mimetypes
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image

from ...core.config import settings
from ...core.schemas import ServerGeneratedImage
from .constants import SERVER_IMAGE_EXTENSIONS
from .errors import ImageGenerationError


logger = logging.getLogger(__name__)


def _image_file_data_url(path: Path) -> str:
    content_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _image_file_thumbnail_data_url(path: Path) -> str:
    try:
        with Image.open(path) as image:
            image.thumbnail((320, 320), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=76, method=4)
    except Exception as exc:
        logger.warning("Failed to create generated image thumbnail for %s: %s", path, exc)
        return _image_file_data_url(path)

    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def _resolve_server_generated_image_path(relative_path: str) -> Path:
    if not relative_path or Path(relative_path).is_absolute():
        raise ImageGenerationError("Invalid generated image path")

    output_dir = Path(settings.comfyui_output_dir).resolve()
    path = (output_dir / relative_path).resolve()
    if path != output_dir and output_dir not in path.parents:
        raise ImageGenerationError("Invalid generated image path")
    if not path.is_file() or path.suffix.lower() not in SERVER_IMAGE_EXTENSIONS:
        raise ImageGenerationError("Generated image was not found")
    return path


def get_server_generated_image_data_url(relative_path: str) -> str:
    return _image_file_data_url(_resolve_server_generated_image_path(relative_path))


def list_server_generated_images(limit: int = 24, include_data: bool = False) -> list[ServerGeneratedImage]:
    output_dir = Path(settings.comfyui_output_dir)
    if not output_dir.exists():
        return []

    candidates = [
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in SERVER_IMAGE_EXTENSIONS
    ]
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    images: list[ServerGeneratedImage] = []
    for path in candidates[: max(min(limit, 48), 1)]:
        stat = path.stat()
        try:
            relative_path = path.relative_to(output_dir).as_posix()
        except ValueError:
            relative_path = path.name
        images.append(
            ServerGeneratedImage(
                filename=path.name,
                relative_path=relative_path,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                thumbnail_data_url=_image_file_thumbnail_data_url(path),
                image_data_url=_image_file_data_url(path) if include_data else None,
            )
        )
    return images
