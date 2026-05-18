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
)
from ..services.comfyui_image_service import (
    ImageGenerationError,
    ImageUpscaleError,
    generate_image_with_e4b,
    upscale_anime_image,
)


router = APIRouter(prefix="/api/images", tags=["images"], dependencies=[Depends(verify_api_token)])
logger = logging.getLogger(__name__)


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
