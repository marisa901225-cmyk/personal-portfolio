from __future__ import annotations

import logging

import requests

from ...core.schemas import ComfyUIImageGenerationRequest, ComfyUIImageGenerationResponse
from ..gpu_work_lock import gpu_heavy_work_lock
from .constants import DEFAULT_UPSCALE_MODEL_NAME
from .errors import ImageGenerationError
from .planner import plan_image_generation
from .workflow import build_workflow, extract_image_entry, fetch_image_data_url, submit_prompt, wait_for_completion


logger = logging.getLogger(__name__)


def _resolve_output_target(request: ComfyUIImageGenerationRequest) -> tuple[int | None, int | None, str | None]:
    if request.output_width is not None or request.output_height is not None:
        if request.output_width is None or request.output_height is None:
            raise ImageGenerationError("output_width and output_height must be provided together")
        return request.output_width, request.output_height, request.upscale_model or DEFAULT_UPSCALE_MODEL_NAME

    lowered = request.request.lower()
    if "4k" in lowered or "uhd" in lowered or "3840" in lowered:
        return 3840, 2160, request.upscale_model or DEFAULT_UPSCALE_MODEL_NAME

    return None, None, None


def generate_image_with_e4b(request: ComfyUIImageGenerationRequest) -> ComfyUIImageGenerationResponse:
    try:
        with gpu_heavy_work_lock("comfyui_generate"):
            llm_model, tool_name, tool_spec = plan_image_generation(request)
            output_width, output_height, upscale_model = _resolve_output_target(request)
            workflow = build_workflow(
                tool_spec,
                output_width=output_width,
                output_height=output_height,
                upscale_model=upscale_model,
            )
            prompt_id = submit_prompt(workflow)
            history = wait_for_completion(prompt_id)
            image_entry = extract_image_entry(history)
            image_data_url = fetch_image_data_url(image_entry)
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
        generated_width=tool_spec.width,
        generated_height=tool_spec.height,
        width=output_width or tool_spec.width,
        height=output_height or tool_spec.height,
        steps=tool_spec.steps,
        cfg=tool_spec.cfg,
        seed=tool_spec.seed,
        prompt_id=prompt_id,
        filename=image_entry["filename"],
        subfolder=image_entry["subfolder"],
        upscale_model=upscale_model,
        image_data_url=image_data_url,
    )
