from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from ...core.config import settings
from ..docker_container_control import DockerSocketError, start_container, stop_container, wait_container_ready

logger = logging.getLogger(__name__)

_MODE_ALWAYS = "always"
_MODE_OFF = "off"


def should_release_local_llm_for_model(model_type: str) -> bool:
    mode = str(settings.comfyui_release_llm_vram_mode or "auto").strip().lower()
    if mode in {_MODE_OFF, "false", "0", "no"}:
        return False
    if mode in {_MODE_ALWAYS, "true", "1", "yes"}:
        return True

    return str(model_type or "").strip().lower() == "realistic"


@contextmanager
def release_local_llm_for_comfyui(model_type: str) -> Iterator[bool]:
    if not should_release_local_llm_for_model(model_type):
        yield False
        return

    container_name = str(settings.comfyui_release_llm_container_name or "").strip()
    if not container_name:
        logger.warning("COMFYUI_RELEASE_LLM_CONTAINER_NAME is empty; skipping local LLM release")
        yield False
        return

    stopped = False
    try:
        stopped = stop_container(
            socket_path=settings.docker_socket_path,
            container_name=container_name,
            timeout_sec=int(settings.comfyui_release_llm_stop_timeout_sec),
        )
        if stopped:
            logger.info("Stopped local LLM container for ComfyUI VRAM: %s", container_name)
        yield stopped
    except DockerSocketError:
        logger.warning("Failed to release local LLM VRAM for ComfyUI", exc_info=True)
        yield False
    finally:
        if not stopped:
            return
        try:
            start_container(socket_path=settings.docker_socket_path, container_name=container_name)
            wait_container_ready(
                socket_path=settings.docker_socket_path,
                container_name=container_name,
                timeout_sec=int(settings.comfyui_release_llm_start_timeout_sec),
            )
            logger.info("Restarted local LLM container after ComfyUI work: %s", container_name)
        except DockerSocketError:
            logger.warning("Failed to restart local LLM container after ComfyUI work", exc_info=True)
