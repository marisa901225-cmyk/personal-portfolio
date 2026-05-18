from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth import verify_api_token
from ..core.rate_limit import rate_limit
from ..core.schemas import (
    AnimeImageUpscaleRequest,
    AnimeImageUpscaleResponse,
    ComfyUIImageGenerationRequest,
    ComfyUIImageGenerationResponse,
    ServerGeneratedImageDataResponse,
    ServerGeneratedImagesResponse,
)
from ..services.comfyui_image_service import (
    get_server_generated_image_data_url,
    ImageGenerationError,
    ImageUpscaleError,
    generate_image_with_e4b,
    list_server_generated_images,
    upscale_anime_image,
)


router = APIRouter(prefix="/api/images", tags=["images"], dependencies=[Depends(verify_api_token)])
logger = logging.getLogger(__name__)


@router.get("/generated", response_model=ServerGeneratedImagesResponse)
def list_generated_images(
    limit: int = 24,
    include_data: bool = False,
    _rate_limit: None = Depends(rate_limit(limit=30, window_sec=60, key_prefix="server_generated_images")),
) -> ServerGeneratedImagesResponse:
    return ServerGeneratedImagesResponse(images=list_server_generated_images(limit=limit, include_data=include_data))


@router.get("/generated/data", response_model=ServerGeneratedImageDataResponse)
def get_generated_image_data(
    path: str,
    _rate_limit: None = Depends(rate_limit(limit=60, window_sec=60, key_prefix="server_generated_image_data")),
) -> ServerGeneratedImageDataResponse:
    try:
        return ServerGeneratedImageDataResponse(image_data_url=get_server_generated_image_data_url(path))
    except ImageGenerationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/generate", response_model=ComfyUIImageGenerationResponse)
def generate_comfyui_image(
    payload: ComfyUIImageGenerationRequest,
    _rate_limit: None = Depends(rate_limit(limit=6, window_sec=60, key_prefix="comfyui_generate")),
) -> ComfyUIImageGenerationResponse:
    try:
        return generate_image_with_e4b(payload)
    except ImageGenerationError as exc:
        logger.exception("ComfyUI image generation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/upscale", response_model=AnimeImageUpscaleResponse)
def upscale_image(
    payload: AnimeImageUpscaleRequest,
    _rate_limit: None = Depends(rate_limit(limit=10, window_sec=60, key_prefix="anime_upscale")),
) -> AnimeImageUpscaleResponse:
    try:
        return upscale_anime_image(payload)
    except ImageUpscaleError as exc:
        logger.exception("Anime image upscale failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
