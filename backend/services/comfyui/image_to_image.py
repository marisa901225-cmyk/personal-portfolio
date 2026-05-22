from __future__ import annotations

import logging

import requests

from ...core.schemas import ComfyUIImageGenerationRequest, ComfyUIImageToImageRequest, ComfyUIImageToImageResponse
from ..gpu_work_lock import gpu_heavy_work_lock
from .errors import ImageGenerationError, ImageUpscaleError
from .planner import plan_image_generation
from .upscale import _decode_image_data_url, _upload_comfyui_input
from .vram_guard import release_local_llm_for_comfyui
from .workflow import build_image_to_image_workflow, extract_image_entry, fetch_image_data_url, submit_prompt, wait_for_completion


logger = logging.getLogger(__name__)


def image_to_image_with_comfyui(request: ComfyUIImageToImageRequest) -> ComfyUIImageToImageResponse:
    try:
        image_bytes, source_ext = _decode_image_data_url(request.image_data_url)
    except ImageUpscaleError as exc:
        raise ImageGenerationError(str(exc)) from exc

    planning_request = ComfyUIImageGenerationRequest(
        request=request.request,
        model_type="anime",
        width=request.width,
        height=request.height,
        seed=request.seed,
        steps=request.steps,
        cfg=request.cfg,
    )

    try:
        with gpu_heavy_work_lock("comfyui_img2img"):
            llm_model, tool_name, tool_spec = plan_image_generation(planning_request)
            input_name = _upload_comfyui_input(image_bytes, source_ext)
            workflow = build_image_to_image_workflow(
                tool_spec,
                input_name=input_name,
                denoise=request.denoise,
            )
            with release_local_llm_for_comfyui("anime"):
                prompt_id = submit_prompt(workflow)
                history = wait_for_completion(prompt_id)
                image_entry = extract_image_entry(history)
                image_data_url = fetch_image_data_url(image_entry)
    except requests.HTTPError as exc:
        body = exc.response.text[:500] if exc.response is not None else ""
        raise ImageGenerationError(f"Upstream image-to-image request failed: {exc}. {body}".strip()) from exc
    except requests.RequestException as exc:
        raise ImageGenerationError(f"Failed to reach e4b or ComfyUI for image-to-image: {exc}") from exc

    logger.info("Generated ComfyUI img2img: prompt_id=%s file=%s", prompt_id, image_entry["filename"])
    return ComfyUIImageToImageResponse(
        request=request.request,
        model_type="anime",
        llm_model=llm_model,
        tool_name=tool_name,
        tool_prompt=tool_spec.prompt,
        negative_prompt=tool_spec.negative_prompt,
        generated_width=tool_spec.width,
        generated_height=tool_spec.height,
        width=tool_spec.width,
        height=tool_spec.height,
        steps=tool_spec.steps,
        cfg=tool_spec.cfg,
        seed=tool_spec.seed,
        prompt_id=prompt_id,
        filename=image_entry["filename"],
        subfolder=image_entry["subfolder"],
        upscale_model=None,
        image_data_url=image_data_url,
        denoise=request.denoise,
    )
