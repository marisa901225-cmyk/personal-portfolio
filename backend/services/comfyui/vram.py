from __future__ import annotations

import json
import logging
import subprocess
import time
from contextlib import contextmanager
from typing import Iterator

import httpx

from ...core.config import settings
from .constants import VRAM_MODE_ALWAYS, VRAM_MODE_AUTO, VRAM_MODE_OFF
from .types import GpuMemory


logger = logging.getLogger(__name__)


def query_gpu_memory() -> GpuMemory | None:
    try:
        completed = subprocess.run(
            [settings.xpu_smi_path, "stats", "-d", "0", "-j"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Failed to query GPU memory with xpu-smi: %s", exc)
        return None

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse xpu-smi JSON output: %s", exc)
        return None

    metrics = data.get("device_level") or []
    values = {
        str(item.get("metrics_type") or ""): item.get("value")
        for item in metrics
        if isinstance(item, dict)
    }
    try:
        used_mb = float(values["XPUM_STATS_MEMORY_USED"])
        utilization_percent = float(values["XPUM_STATS_MEMORY_UTILIZATION"])
    except (KeyError, TypeError, ValueError):
        logger.warning("xpu-smi output did not include memory used/utilization metrics")
        return None

    return GpuMemory(used_mb=used_mb, utilization_percent=utilization_percent)


def _docker_client() -> httpx.Client:
    transport = httpx.HTTPTransport(uds=settings.docker_socket_path)
    return httpx.Client(transport=transport, base_url="http://docker", timeout=20.0)


def _get_container_state(client: httpx.Client, container_name: str) -> tuple[str | None, bool]:
    response = client.get(f"/containers/{container_name}/json")
    if response.status_code == 404:
        return None, False
    response.raise_for_status()
    data = response.json() or {}
    state = data.get("State") or {}
    return str(data.get("Id") or ""), bool(state.get("Running"))


def set_container_running(container_name: str, should_run: bool) -> bool:
    action = "start" if should_run else "stop"
    with _docker_client() as client:
        container_id, running = _get_container_state(client, container_name)
        if not container_id:
            logger.warning("ComfyUI container not found for VRAM control: %s", container_name)
            return False
        if running == should_run:
            return False

        params = {"t": 10} if action == "stop" else None
        response = client.post(f"/containers/{container_id}/{action}", params=params)
        if response.status_code not in {204, 304}:
            response.raise_for_status()
        return True


def should_stop_comfyui_for_upscale() -> bool:
    mode = (settings.realesrgan_comfyui_vram_mode or VRAM_MODE_AUTO).strip().lower()
    if mode == VRAM_MODE_OFF:
        return False
    if mode == VRAM_MODE_ALWAYS:
        return True

    gpu_memory = query_gpu_memory()
    if gpu_memory is None:
        return False
    estimated_free_mb = gpu_memory.estimated_free_mb
    if estimated_free_mb is None:
        return False

    should_stop = estimated_free_mb < settings.realesrgan_min_free_vram_mb
    logger.info(
        "Anime upscale VRAM check: used=%.1fMB util=%.1f%% free≈%.1fMB threshold=%.1fMB stop_comfyui=%s",
        gpu_memory.used_mb,
        gpu_memory.utilization_percent,
        estimated_free_mb,
        settings.realesrgan_min_free_vram_mb,
        should_stop,
    )
    return should_stop


@contextmanager
def comfyui_vram_guard() -> Iterator[None]:
    stopped = False
    if should_stop_comfyui_for_upscale():
        stopped = set_container_running(settings.realesrgan_comfyui_container_name, should_run=False)
        if stopped:
            logger.info("Stopped ComfyUI before anime upscaling to free VRAM.")
            time.sleep(2.0)
    try:
        yield
    finally:
        if stopped:
            try:
                set_container_running(settings.realesrgan_comfyui_container_name, should_run=True)
                logger.info("Restarted ComfyUI after anime upscaling.")
            except Exception:
                logger.exception("Failed to restart ComfyUI after anime upscaling")
