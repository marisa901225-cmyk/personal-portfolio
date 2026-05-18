from __future__ import annotations

import base64
import json
import os

import pytest
from PIL import Image

from backend.core.schemas import AnimeImageUpscaleRequest, ComfyUIImageGenerationRequest
from backend.services.comfyui_image_service import (
    ImageGenerationError,
    _GpuMemory,
    generate_image_with_e4b,
    get_server_generated_image_data_url,
    list_server_generated_images,
    upscale_anime_image,
)


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


def test_upscale_anime_image_runs_realesrgan_model(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tool_dir = tmp_path / "realesrgan"
    models_dir = tool_dir / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "realesrgan-x4plus-anime.bin").write_bytes(b"model")
    (models_dir / "realesrgan-x4plus-anime.param").write_text("param", encoding="utf-8")

    bin_path = tool_dir / "realesrgan-ncnn-vulkan"
    bin_path.write_text(
        "#!/usr/bin/env bash\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  case \"$1\" in\n"
        "    -i) input=\"$2\"; shift 2 ;;\n"
        "    -o) output=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "cp \"$input\" \"$output\"\n",
        encoding="utf-8",
    )
    bin_path.chmod(0o755)

    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps({"models": [{"id": "realesrgan-x4plus-anime", "scale": 4}]}),
        encoding="utf-8",
    )

    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_bin_path", str(bin_path))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_model_dir", str(tool_dir))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_models_config_path", str(config_path))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_timeout_sec", 5)
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_comfyui_vram_mode", "off")

    source_path = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(source_path)
    source_bytes = source_path.read_bytes()
    result = upscale_anime_image(
        AnimeImageUpscaleRequest(
            image_data_url=f"data:image/png;base64,{base64.b64encode(source_bytes).decode('ascii')}",
            model="realesrgan-x4plus-anime",
            scale=4,
        )
    )

    assert result.model == "realesrgan-x4plus-anime"
    assert result.scale == 4
    assert result.width == 2
    assert result.height == 2
    assert result.filename == "anime_upscaled_x4.png"
    assert result.image_data_url == f"data:image/png;base64,{base64.b64encode(source_bytes).decode('ascii')}"


def test_upscale_anime_image_resizes_to_target_resolution(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tool_dir = tmp_path / "realesrgan"
    models_dir = tool_dir / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "realesrgan-x4plus-anime.bin").write_bytes(b"model")
    (models_dir / "realesrgan-x4plus-anime.param").write_text("param", encoding="utf-8")

    bin_path = tool_dir / "realesrgan-ncnn-vulkan"
    bin_path.write_text(
        "#!/usr/bin/env bash\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  case \"$1\" in\n"
        "    -i) input=\"$2\"; shift 2 ;;\n"
        "    -o) output=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "cp \"$input\" \"$output\"\n",
        encoding="utf-8",
    )
    bin_path.chmod(0o755)

    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps({"models": [{"id": "realesrgan-x4plus-anime", "scale": 4}]}),
        encoding="utf-8",
    )

    source_path = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(source_path)
    source_bytes = source_path.read_bytes()

    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_bin_path", str(bin_path))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_model_dir", str(tool_dir))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_models_config_path", str(config_path))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_timeout_sec", 5)
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_comfyui_vram_mode", "off")

    result = upscale_anime_image(
        AnimeImageUpscaleRequest(
            image_data_url=f"data:image/png;base64,{base64.b64encode(source_bytes).decode('ascii')}",
            model="realesrgan-x4plus-anime",
            scale=4,
            target_width=256,
            target_height=256,
        )
    )

    assert result.width == 256
    assert result.height == 256
    encoded = result.image_data_url.split(",", 1)[1]
    output_path = tmp_path / "output.png"
    output_path.write_bytes(base64.b64decode(encoded))
    with Image.open(output_path) as image:
        assert image.size == (256, 256)


def test_upscale_anime_image_stops_comfyui_when_vram_is_low(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    tool_dir = tmp_path / "realesrgan"
    models_dir = tool_dir / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "realesrgan-x4plus-anime.bin").write_bytes(b"model")
    (models_dir / "realesrgan-x4plus-anime.param").write_text("param", encoding="utf-8")

    bin_path = tool_dir / "realesrgan-ncnn-vulkan"
    bin_path.write_text(
        "#!/usr/bin/env bash\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  case \"$1\" in\n"
        "    -i) input=\"$2\"; shift 2 ;;\n"
        "    -o) output=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "cp \"$input\" \"$output\"\n",
        encoding="utf-8",
    )
    bin_path.chmod(0o755)

    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps({"models": [{"id": "realesrgan-x4plus-anime", "scale": 4}]}),
        encoding="utf-8",
    )

    calls: list[bool] = []
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_bin_path", str(bin_path))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_model_dir", str(tool_dir))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_models_config_path", str(config_path))
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_timeout_sec", 5)
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_comfyui_vram_mode", "auto")
    monkeypatch.setattr("backend.services.comfyui_image_service.settings.realesrgan_min_free_vram_mb", 1536.0)
    monkeypatch.setattr(
        "backend.services.comfyui_image_service._query_gpu_memory",
        lambda: _GpuMemory(used_mb=10_928.0, utilization_percent=91.62),
    )
    monkeypatch.setattr(
        "backend.services.comfyui_image_service._set_container_running",
        lambda _container_name, *, should_run: calls.append(should_run) or True,
    )

    source_path = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(source_path)
    source_bytes = source_path.read_bytes()
    result = upscale_anime_image(
        AnimeImageUpscaleRequest(
            image_data_url=f"data:image/png;base64,{base64.b64encode(source_bytes).decode('ascii')}",
            model="realesrgan-x4plus-anime",
            scale=4,
        )
    )

    assert result.filename == "anime_upscaled_x4.png"
    assert calls == [False, True]
