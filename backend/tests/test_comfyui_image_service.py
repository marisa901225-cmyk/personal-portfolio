from __future__ import annotations

import base64
import json
import os

import pytest
from PIL import Image

from backend.core.schemas import AnimeImageUpscaleRequest, ComfyUIImageGenerationRequest
from backend.services.comfyui_image_service import (
    ImageGenerationError,
    generate_image_with_e4b,
    get_server_generated_image_data_url,
    list_server_generated_images,
    upscale_anime_image,
)
from backend.services.comfyui.types import ToolSpec
from backend.services.comfyui.planner import _build_image_planner_payload, _llm_base_url_candidates
import backend.services.comfyui.generation as generation_module
import backend.services.comfyui.vram_guard as vram_guard_module
from backend.services.comfyui.workflow import build_workflow
import backend.services.comfyui.upscale as upscale_module


class _Response:
    def __init__(self, *, json_data=None, content: bytes = b"", status_code: int = 200, headers=None, text: str = ""):
        self._json_data = json_data
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._json_data


def test_generate_image_with_e4b_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_base_url", "http://llm.test")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_remote_default_model", "cq_gemma4_e4b_q8.gguf")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.open_api_key", None)
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.comfyui_base_url", "http://comfy.test")

    image_bytes = b"\x89PNG\r\nfake"
    llm_response = _Response(
        json_data={
            "model": "cq_gemma4_e4b_q8.gguf",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "generate_comfyui_image",
                                    "arguments": (
                                        '{"prompt":"warm cat by the window, storybook illustration",'
                                        '"negative_prompt":"blurry",'
                                        '"width":896,"height":1152,"steps":24,"cfg":4.5,"seed":12345}'
                                    ),
                                }
                            }
                        ]
                    }
                }
            ],
        }
    )
    prompt_response = _Response(json_data={"prompt_id": "abc-123"})
    history_response = _Response(
        json_data={
            "abc-123": {
                "status": {"completed": True},
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "e4b_comfyui_00001_.png", "subfolder": "", "type": "output"}
                        ]
                    }
                },
            }
        }
    )
    view_response = _Response(content=image_bytes, headers={"Content-Type": "image/png"})

    post_calls: list[tuple[str, dict]] = []
    get_calls: list[tuple[str, dict]] = []

    def fake_post(url: str, **kwargs):
        post_calls.append((url, kwargs))
        if url.endswith("/v1/chat/completions"):
            return llm_response
        if url.endswith("/prompt"):
            return prompt_response
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, **kwargs):
        get_calls.append((url, kwargs))
        if url.endswith("/v1/models"):
            return _Response(json_data={"data": [{"id": "cq_gemma4_e4b_q8.gguf"}]})
        if url.endswith("/history/abc-123"):
            return history_response
        if url.endswith("/view"):
            return view_response
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("backend.services.comfyui_image_service.requests.post", fake_post)
    monkeypatch.setattr("backend.services.comfyui_image_service.requests.get", fake_get)

    result = generate_image_with_e4b(
        ComfyUIImageGenerationRequest(request="창가에서 자는 고양이 일러스트", width=1024, height=1024)
    )

    assert result.prompt_id == "abc-123"
    assert result.tool_name == "generate_comfyui_image"
    assert result.width == 896
    assert result.height == 1152
    assert result.steps == 24
    assert result.seed == 12345
    assert result.filename == "e4b_comfyui_00001_.png"
    assert result.image_data_url == f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"

    workflow = post_calls[1][1]["json"]["prompt"]
    assert workflow["5"]["inputs"]["text"] == "warm cat by the window, storybook illustration"
    assert workflow["7"]["inputs"]["seed"] == 12345

    params = get_calls[2][1]["params"]
    assert params["filename"] == "e4b_comfyui_00001_.png"


def test_image_planner_prefers_8084_before_stale_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui.planner.settings.llm_base_url", "http://openvino-server:8082")

    assert _llm_base_url_candidates() == [
        "http://llama-server-sycl-huihui:8084",
        "http://127.0.0.1:8084",
        "http://localhost:8084",
        "http://openvino-server:8082",
    ]


def test_image_planner_payload_loads_shared_ultrareal_prompt() -> None:
    request = ComfyUIImageGenerationRequest(request="비 오는 골목의 검은 우산", width=1024, height=1024)

    payload = _build_image_planner_payload(request, model="local-model.gguf")

    system_prompt = payload["messages"][0]["content"]
    assert "UltraReal FineTune Anima" in system_prompt
    assert "Always call the generate_comfyui_image tool" in system_prompt
    assert "rain-soaked alley" in system_prompt


def test_image_planner_json_payload_loads_shared_ultrareal_prompt() -> None:
    request = ComfyUIImageGenerationRequest(request="창가에서 자는 고양이", width=1024, height=1024)

    payload = _build_image_planner_payload(request, model="google/gemma-4-31b-it", prefer_json_content=True)

    system_prompt = payload["messages"][0]["content"]
    assert payload["response_format"] == {"type": "json_object"}
    assert "Return JSON only" in system_prompt
    assert "UltraReal FineTune Anima" in system_prompt


def test_generate_image_with_e4b_normalizes_negative_llm_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_base_url", "http://llm.test")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_remote_default_model", "local-model.gguf")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.open_api_key", None)
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.comfyui_base_url", "http://comfy.test")
    monkeypatch.setattr("backend.services.comfyui.planner._llm_base_url_candidates", lambda: ["http://llm.test"])
    monkeypatch.setattr("backend.services.comfyui.planner.random.randint", lambda _start, _end: 123456)

    llm_response = _Response(
        json_data={
            "model": "local-model.gguf",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "prompt": "cosplay portrait",
                                "width": 1024,
                                "height": 1024,
                                "seed": -1,
                            }
                        )
                    }
                }
            ],
        }
    )
    prompt_response = _Response(json_data={"prompt_id": "seed-123"})
    history_response = _Response(
        json_data={
            "seed-123": {
                "status": {"completed": True},
                "outputs": {"9": {"images": [{"filename": "seed.png", "subfolder": "", "type": "output"}]}},
            }
        }
    )
    view_response = _Response(content=b"\x89PNG\r\nseed", headers={"Content-Type": "image/png"})

    def fake_post(url: str, **kwargs):
        if url == "http://llm.test/v1/chat/completions":
            return llm_response
        if url == "http://comfy.test/prompt":
            return prompt_response
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, **kwargs):
        if url == "http://llm.test/v1/models":
            return _Response(json_data={"data": [{"id": "local-model.gguf"}]})
        if url.endswith("/history/seed-123"):
            return history_response
        if url.endswith("/view"):
            return view_response
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("backend.services.comfyui_image_service.requests.post", fake_post)
    monkeypatch.setattr("backend.services.comfyui_image_service.requests.get", fake_get)

    result = generate_image_with_e4b(ComfyUIImageGenerationRequest(request="seed test", width=1024, height=1024))

    assert result.seed == 123456


def test_generate_image_with_e4b_uses_request_cfg_over_planner_cfg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_base_url", "http://llm.test")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_remote_default_model", "local-model.gguf")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.open_api_key", None)
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.comfyui_base_url", "http://comfy.test")
    monkeypatch.setattr("backend.services.comfyui.planner._llm_base_url_candidates", lambda: ["http://llm.test"])

    llm_response = _Response(
        json_data={
            "model": "local-model.gguf",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "prompt": "anime city",
                                "width": 1024,
                                "height": 1024,
                                "steps": 20,
                                "cfg": 9.5,
                                "seed": 77,
                            }
                        )
                    }
                }
            ],
        }
    )
    prompt_response = _Response(json_data={"prompt_id": "cfg-123"})
    history_response = _Response(
        json_data={
            "cfg-123": {
                "status": {"completed": True},
                "outputs": {"9": {"images": [{"filename": "cfg.png", "subfolder": "", "type": "output"}]}},
            }
        }
    )
    view_response = _Response(content=b"\x89PNG\r\ncfg", headers={"Content-Type": "image/png"})

    def fake_post(url: str, **kwargs):
        if url == "http://llm.test/v1/chat/completions":
            return llm_response
        if url == "http://comfy.test/prompt":
            return prompt_response
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, **kwargs):
        if url == "http://llm.test/v1/models":
            return _Response(json_data={"data": [{"id": "local-model.gguf"}]})
        if url.endswith("/history/cfg-123"):
            return history_response
        if url.endswith("/view"):
            return view_response
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("backend.services.comfyui_image_service.requests.post", fake_post)
    monkeypatch.setattr("backend.services.comfyui_image_service.requests.get", fake_get)

    result = generate_image_with_e4b(
        ComfyUIImageGenerationRequest(request="cfg override test", width=1024, height=1024, cfg=2.5)
    )

    assert result.cfg == 2.5


def test_generate_image_with_e4b_retries_local_tool_call_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_base_url", "http://llm.test")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_remote_default_model", "local-model.gguf")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.open_api_key", None)
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.comfyui_base_url", "http://comfy.test")
    monkeypatch.setattr("backend.services.comfyui.planner._llm_base_url_candidates", lambda: ["http://llm.test"])

    bad_llm_response = _Response(
        json_data={
            "model": "local-model.gguf",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "generate_comfyui_image", "arguments": '{"prompt": "broken'}}
                        ]
                    }
                }
            ],
        }
    )
    good_llm_response = _Response(
        json_data={
            "model": "local-model.gguf",
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "generate_comfyui_image",
                                    "arguments": '{"prompt":"stable prompt","width":1024,"height":1024,"seed":7}',
                                }
                            }
                        ]
                    }
                }
            ],
        }
    )
    prompt_response = _Response(json_data={"prompt_id": "retry-123"})
    history_response = _Response(
        json_data={
            "retry-123": {
                "status": {"completed": True},
                "outputs": {"9": {"images": [{"filename": "retry.png", "subfolder": "", "type": "output"}]}},
            }
        }
    )
    view_response = _Response(content=b"\x89PNG\r\nretry", headers={"Content-Type": "image/png"})
    llm_post_count = 0

    def fake_post(url: str, **kwargs):
        nonlocal llm_post_count
        if url == "http://llm.test/v1/chat/completions":
            llm_post_count += 1
            return bad_llm_response if llm_post_count == 1 else good_llm_response
        if url == "http://comfy.test/prompt":
            return prompt_response
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, **kwargs):
        if url == "http://llm.test/v1/models":
            return _Response(json_data={"data": [{"id": "local-model.gguf"}]})
        if url.endswith("/history/retry-123"):
            return history_response
        if url.endswith("/view"):
            return view_response
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr("backend.services.comfyui_image_service.requests.post", fake_post)
    monkeypatch.setattr("backend.services.comfyui_image_service.requests.get", fake_get)

    result = generate_image_with_e4b(ComfyUIImageGenerationRequest(request="retry test", width=1024, height=1024))

    assert llm_post_count == 2
    assert result.tool_prompt == "stable prompt"
    assert result.seed == 7


def test_build_workflow_routes_4k_output_through_upscale_model() -> None:
    workflow = build_workflow(
        ToolSpec(
            prompt="anime character under neon rain",
            negative_prompt="blurry",
            width=1024,
            height=1024,
            steps=20,
            cfg=4.0,
            seed=123,
        ),
        output_width=3840,
        output_height=2160,
        upscale_model="RealESRGAN_x4plus.pth",
    )

    assert workflow["10"]["class_type"] == "UpscaleModelLoader"
    assert workflow["10"]["inputs"]["model_name"] == "RealESRGAN_x4plus.pth"
    assert workflow["11"]["class_type"] == "ImageUpscaleWithModel"
    assert workflow["12"]["inputs"]["width"] == 3840
    assert workflow["12"]["inputs"]["height"] == 2160
    assert workflow["9"]["inputs"]["images"] == ["12", 0]


def test_build_workflow_uses_anima_loras_for_anime_mode() -> None:
    workflow = build_workflow(
        ToolSpec(
            prompt="anime character under neon rain",
            negative_prompt="blurry",
            width=1024,
            height=1024,
            steps=10,
            cfg=1.0,
            seed=123,
        ),
    )

    assert workflow["13"] == {
        "class_type": "LoraLoader",
        "inputs": {
            "model": ["1", 0],
            "clip": ["2", 0],
            "lora_name": "anima-turbo-lora-v0.1.safetensors",
            "strength_model": 1.0,
            "strength_clip": 1.0,
        },
    }
    assert workflow["14"] == {
        "class_type": "LoraLoader",
        "inputs": {
            "model": ["13", 0],
            "clip": ["13", 1],
            "lora_name": "anima-highres-aesthetic-boost.safetensors",
            "strength_model": 1.0,
            "strength_clip": 1.0,
        },
    }
    assert workflow["5"]["inputs"]["clip"] == ["14", 1]
    assert workflow["6"]["inputs"]["clip"] == ["14", 1]
    assert workflow["7"]["inputs"]["model"] == ["14", 0]


def test_vram_guard_releases_only_for_explicit_realistic_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vram_guard_module.settings, "comfyui_release_llm_vram_mode", "auto")

    assert vram_guard_module.should_release_local_llm_for_model("realistic")
    assert not vram_guard_module.should_release_local_llm_for_model("anime")


def test_generate_image_releases_local_llm_after_planning_for_realistic_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(vram_guard_module.settings, "comfyui_release_llm_vram_mode", "auto")
    monkeypatch.setattr(vram_guard_module.settings, "comfyui_release_llm_container_name", "llm-test")
    monkeypatch.setattr(vram_guard_module.settings, "docker_socket_path", "/var/run/docker.sock")

    monkeypatch.setattr(
        generation_module,
        "plan_image_generation",
        lambda _request: (
            "local-model.gguf",
            "generate_comfyui_image",
            ToolSpec(
                prompt="photorealistic city street at night",
                negative_prompt="blurry",
                width=1024,
                height=1024,
                steps=20,
                cfg=4.0,
                seed=11,
            ),
        ),
    )
    monkeypatch.setattr(
        vram_guard_module,
        "stop_container",
        lambda **_kwargs: calls.append("stop") or True,
    )
    monkeypatch.setattr(
        vram_guard_module,
        "start_container",
        lambda **_kwargs: calls.append("start"),
    )
    monkeypatch.setattr(
        vram_guard_module,
        "wait_container_ready",
        lambda **_kwargs: calls.append("ready"),
    )
    monkeypatch.setattr(generation_module, "submit_prompt", lambda _workflow: calls.append("submit") or "prompt-1")
    monkeypatch.setattr(
        generation_module,
        "wait_for_completion",
        lambda _prompt_id: calls.append("wait") or {"outputs": {}},
    )
    monkeypatch.setattr(
        generation_module,
        "extract_image_entry",
        lambda _history: {"filename": "city.png", "subfolder": "", "type": "output"},
    )
    monkeypatch.setattr(
        generation_module,
        "fetch_image_data_url",
        lambda _entry: calls.append("fetch") or "data:image/png;base64,ZmFrZQ==",
    )

    result = generate_image_with_e4b(
        ComfyUIImageGenerationRequest(
            request="z-image turbo로 실사 도시 야경",
            model_type="realistic",
            width=1024,
            height=1024,
        )
    )

    assert result.filename == "city.png"
    assert result.model_type == "realistic"
    assert calls == ["stop", "submit", "wait", "fetch", "start", "ready"]


def test_build_workflow_uses_z_image_turbo_for_realistic_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui.workflow.settings.comfyui_z_image_unet_name", "z-image-turbo-fp8-e4m3fn.safetensors")
    monkeypatch.setattr("backend.services.comfyui.workflow.settings.comfyui_z_image_clip_name", "qwen3-4b-fp8-scaled.safetensors")
    monkeypatch.setattr("backend.services.comfyui.workflow.settings.comfyui_z_image_vae_name", "ae.safetensors")

    workflow = build_workflow(
        ToolSpec(
            prompt="photorealistic city at night",
            negative_prompt="blurry",
            width=1024,
            height=1024,
            steps=8,
            cfg=1.0,
            seed=123,
        ),
        model_type="realistic",
    )

    assert workflow["1"]["inputs"] == {
        "unet_name": "z-image-turbo-fp8-e4m3fn.safetensors",
        "weight_dtype": "fp8_e4m3fn",
    }
    assert workflow["2"]["inputs"]["clip_name"] == "qwen3-4b-fp8-scaled.safetensors"
    assert workflow["2"]["inputs"]["type"] == "lumina2"
    assert workflow["3"]["inputs"]["vae_name"] == "ae.safetensors"
    assert workflow["7"]["class_type"] == "ModelSamplingAuraFlow"
    assert workflow["8"]["inputs"]["steps"] == 8
    assert workflow["8"]["inputs"]["cfg"] == 1.0


def test_generate_image_with_e4b_falls_back_to_openrouter_gemma(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_base_url", "http://llm.test")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_remote_default_model", "local-model.gguf")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.open_api_key", "openrouter-key")
    monkeypatch.setattr(
        "backend.services.comfyui_image_service.settings.image_generation_openrouter_base_url",
        "https://openrouter.test/api/v1",
    )
    monkeypatch.setattr(
        "backend.services.comfyui_image_service.settings.image_generation_openrouter_model",
        "google/gemma-4-31b-it",
    )
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.comfyui_base_url", "http://comfy.test")

    image_bytes = b"\x89PNG\r\nfallback"
    openrouter_response = _Response(
        json_data={
            "model": "google/gemma-4-31b-it",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "prompt": "cinematic anime alley in the rain, black umbrella",
                                "negative_prompt": "blurry",
                                "width": 1024,
                                "height": 1024,
                                "steps": 20,
                                "cfg": 4,
                                "seed": 999,
                            }
                        )
                    }
                }
            ],
        }
    )
    prompt_response = _Response(json_data={"prompt_id": "fallback-123"})
    history_response = _Response(
        json_data={
            "fallback-123": {
                "status": {"completed": True},
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": "ai_comfyui_00001_.png", "subfolder": "", "type": "output"}
                        ]
                    }
                },
            }
        }
    )
    view_response = _Response(content=image_bytes, headers={"Content-Type": "image/png"})

    post_calls: list[tuple[str, dict]] = []

    def fake_post(url: str, **kwargs):
        post_calls.append((url, kwargs))
        if url in {
            "http://llm.test/v1/chat/completions",
            "http://llama-server-sycl-huihui:8084/v1/chat/completions",
            "http://127.0.0.1:8084/v1/chat/completions",
            "http://localhost:8084/v1/chat/completions",
        }:
            raise requests.ConnectionError("local llm down")
        if url == "https://openrouter.test/api/v1/chat/completions":
            return openrouter_response
        if url == "http://comfy.test/prompt":
            return prompt_response
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url: str, **kwargs):
        if url in {
            "http://llm.test/v1/models",
            "http://llama-server-sycl-huihui:8084/v1/models",
            "http://127.0.0.1:8084/v1/models",
            "http://localhost:8084/v1/models",
        }:
            raise requests.ConnectionError("local llm down")
        if url.endswith("/history/fallback-123"):
            return history_response
        if url.endswith("/view"):
            return view_response
        raise AssertionError(f"unexpected GET {url}")

    import requests

    monkeypatch.setattr("backend.services.comfyui_image_service.requests.post", fake_post)
    monkeypatch.setattr("backend.services.comfyui_image_service.requests.get", fake_get)

    result = generate_image_with_e4b(
        ComfyUIImageGenerationRequest(request="비 오는 골목의 검은 우산", width=1024, height=1024)
    )

    assert result.llm_model == "google/gemma-4-31b-it"
    assert result.tool_prompt == "cinematic anime alley in the rain, black umbrella"
    assert result.seed == 999
    assert result.filename == "ai_comfyui_00001_.png"
    openrouter_call = next(call for call in post_calls if call[0] == "https://openrouter.test/api/v1/chat/completions")
    assert openrouter_call[1]["headers"]["Authorization"] == "Bearer openrouter-key"


def test_generate_image_with_e4b_requires_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_base_url", "http://llm.test")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.llm_remote_default_model", "cq_gemma4_e4b_q8.gguf")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.open_api_key", None)

    llm_response = _Response(
        json_data={
            "model": "cq_gemma4_e4b_q8.gguf",
            "choices": [{"message": {"content": "직접 설명만 드릴게요"}}],
        }
    )

    monkeypatch.setattr("backend.services.comfyui_image_service.requests.post", lambda *args, **kwargs: llm_response)
    monkeypatch.setattr(
        "backend.services.comfyui_image_service.requests.get",
        lambda *args, **kwargs: _Response(json_data={"data": [{"id": "cq_gemma4_e4b_q8.gguf"}]}),
    )

    with pytest.raises(ImageGenerationError, match="did not produce a ComfyUI tool call"):
        generate_image_with_e4b(ComfyUIImageGenerationRequest(request="고양이 그림", width=1024, height=1024))


def test_list_server_generated_images_reads_recent_output(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    output_dir = tmp_path / "output"
    nested_dir = output_dir / "sub"
    nested_dir.mkdir(parents=True)
    older = output_dir / "older.png"
    newer = nested_dir / "newer.webp"
    ignored = output_dir / "note.txt"
    older.write_bytes(b"\x89PNG\r\nolder")
    newer.write_bytes(b"WEBP")
    ignored.write_text("skip", encoding="utf-8")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.comfyui_output_dir", str(output_dir))

    images = list_server_generated_images(limit=10)

    assert [image.relative_path for image in images] == ["sub/newer.webp", "older.png"]
    assert images[0].filename == "newer.webp"
    assert images[0].thumbnail_data_url.startswith("data:image/webp;base64,")
    assert images[0].image_data_url is None
    assert images[1].thumbnail_data_url.startswith("data:image/png;base64,")

    images_with_data = list_server_generated_images(limit=1, include_data=True)

    assert images_with_data[0].image_data_url == f"data:image/webp;base64,{base64.b64encode(b'WEBP').decode('ascii')}"


def test_get_server_generated_image_data_url_rejects_path_escape(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "ok.png").write_bytes(b"\x89PNG\r\nok")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"secret")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.comfyui_output_dir", str(output_dir))

    assert get_server_generated_image_data_url("ok.png").startswith("data:image/png;base64,")
    with pytest.raises(ImageGenerationError, match="Invalid generated image path"):
        get_server_generated_image_data_url("../outside.png")


def test_upscale_anime_image_uses_comfyui_upscale_nodes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(source_path)
    source_bytes = source_path.read_bytes()
    output_path = tmp_path / "output.png"
    Image.new("RGB", (256, 256), "blue").save(output_path)
    output_data_url = f"data:image/png;base64,{base64.b64encode(output_path.read_bytes()).decode('ascii')}"
    submitted: dict[str, dict] = {}

    monkeypatch.setattr(upscale_module, "_upload_comfyui_input", lambda _bytes, _ext: "source.png")
    monkeypatch.setattr(upscale_module, "submit_prompt", lambda workflow: submitted.setdefault("workflow", workflow) or "prompt-1")
    monkeypatch.setattr(upscale_module, "wait_for_completion", lambda _prompt_id, timeout_sec=180: {"outputs": {}})
    monkeypatch.setattr(upscale_module, "extract_image_entry", lambda _history: {"filename": "anime_upscaled_00001_.png", "subfolder": "", "type": "output"})
    monkeypatch.setattr(upscale_module, "fetch_image_data_url", lambda _entry: output_data_url)

    result = upscale_anime_image(
        AnimeImageUpscaleRequest(
            image_data_url=f"data:image/png;base64,{base64.b64encode(source_bytes).decode('ascii')}",
            model="realesrgan-x4plus-anime",
            scale=4,
            target_width=256,
            target_height=256,
        )
    )

    workflow = submitted["workflow"]
    assert workflow["1"]["class_type"] == "LoadImage"
    assert workflow["2"]["inputs"]["model_name"] == "RealESRGAN_x4plus_anime_6B.pth"
    assert workflow["3"]["class_type"] == "ImageUpscaleWithModel"
    assert workflow["4"]["inputs"]["width"] == 256
    assert workflow["4"]["inputs"]["height"] == 256
    assert workflow["5"]["inputs"]["images"] == ["4", 0]
    assert result.model == "RealESRGAN_x4plus_anime_6B.pth"
    assert result.width == 256
    assert result.height == 256


def test_upscale_anime_image_supports_general_realesrgan_alias(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(source_path)
    output_path = tmp_path / "output.png"
    Image.new("RGB", (8, 8), "green").save(output_path)
    output_data_url = f"data:image/png;base64,{base64.b64encode(output_path.read_bytes()).decode('ascii')}"
    submitted: dict[str, dict] = {}

    monkeypatch.setattr(upscale_module, "_upload_comfyui_input", lambda _bytes, _ext: "source.png")
    monkeypatch.setattr(upscale_module, "submit_prompt", lambda workflow: submitted.setdefault("workflow", workflow) or "prompt-1")
    monkeypatch.setattr(upscale_module, "wait_for_completion", lambda _prompt_id, timeout_sec=180: {"outputs": {}})
    monkeypatch.setattr(upscale_module, "extract_image_entry", lambda _history: {"filename": "upscaled_00001_.png", "subfolder": "", "type": "output"})
    monkeypatch.setattr(upscale_module, "fetch_image_data_url", lambda _entry: output_data_url)

    result = upscale_anime_image(
        AnimeImageUpscaleRequest(
            image_data_url=f"data:image/png;base64,{base64.b64encode(source_path.read_bytes()).decode('ascii')}",
            model="realesrgan-x4plus",
            scale=4,
        )
    )

    assert submitted["workflow"]["2"]["inputs"]["model_name"] == "RealESRGAN_x4plus.pth"
    assert result.model == "RealESRGAN_x4plus.pth"


def test_upscale_anime_image_runs_native_model_size_without_target(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    source_path = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(source_path)
    output_path = tmp_path / "output.png"
    Image.new("RGB", (8, 8), "green").save(output_path)
    output_data_url = f"data:image/png;base64,{base64.b64encode(output_path.read_bytes()).decode('ascii')}"
    submitted: dict[str, dict] = {}

    monkeypatch.setattr(upscale_module, "_upload_comfyui_input", lambda _bytes, _ext: "source.png")
    monkeypatch.setattr(upscale_module, "submit_prompt", lambda workflow: submitted.setdefault("workflow", workflow) or "prompt-1")
    monkeypatch.setattr(upscale_module, "wait_for_completion", lambda _prompt_id, timeout_sec=180: {"outputs": {}})
    monkeypatch.setattr(upscale_module, "extract_image_entry", lambda _history: {"filename": "anime_upscaled_00001_.png", "subfolder": "", "type": "output"})
    monkeypatch.setattr(upscale_module, "fetch_image_data_url", lambda _entry: output_data_url)

    result = upscale_anime_image(
        AnimeImageUpscaleRequest(
            image_data_url=f"data:image/png;base64,{base64.b64encode(source_path.read_bytes()).decode('ascii')}",
            model="realesrgan-x4plus-anime",
            scale=4,
        )
    )

    assert "4" not in submitted["workflow"]
    assert submitted["workflow"]["5"]["inputs"]["images"] == ["3", 0]
    assert result.width == 8
    assert result.height == 8
    assert result.filename == "anime_upscaled_x4.png"
