from __future__ import annotations

import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

AutoTokenizer = Any  # type: ignore[misc,assignment]
OVModelForCausalLM = Any  # type: ignore[misc,assignment]


MODEL_DIR = os.getenv(
    "OV_MODEL_DIR",
    "/models/Josiefied-Qwen3-8B-int8",
)
MODEL_ID = os.getenv("OV_MODEL_ID", os.path.basename(MODEL_DIR.rstrip("/")))
DEVICE = os.getenv("OV_DEVICE", "GPU")

app = FastAPI(title="OpenVINO OpenAI-Compatible Server")

_tokenizer: AutoTokenizer | None = None
_model: OVModelForCausalLM | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    max_tokens: int = Field(default=128, ge=1, le=2048)
    temperature: float | None = 0.0
    top_p: float | None = 0.95
    stop: str | list[str] | None = None
    stream: bool = False
    chat_template_kwargs: dict[str, Any] | None = None


def _ensure_loaded() -> tuple[AutoTokenizer, OVModelForCausalLM]:
    global _tokenizer, _model
    if _tokenizer is None or _model is None:
        try:
            from transformers import AutoTokenizer as _AutoTokenizer  # type: ignore
            from optimum.intel.openvino import OVModelForCausalLM as _OVModelForCausalLM  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime env dependent
            raise RuntimeError(f"OpenVINO dependencies are not available: {exc}")

        globals()["AutoTokenizer"] = _AutoTokenizer
        globals()["OVModelForCausalLM"] = _OVModelForCausalLM

    if _tokenizer is None:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    if _model is None:
        _model = OVModelForCausalLM.from_pretrained(MODEL_DIR, device=DEVICE)
    return _tokenizer, _model


def _messages_to_prompt(
    tokenizer: AutoTokenizer,
    messages: list[ChatMessage],
    template_kwargs: dict[str, Any] | None = None,
) -> str:
    raw = [{"role": m.role, "content": m.content} for m in messages]
    if hasattr(tokenizer, "apply_chat_template"):
        kwargs = dict(template_kwargs or {})
        try:
            return tokenizer.apply_chat_template(
                raw,
                tokenize=False,
                add_generation_prompt=True,
                **kwargs,
            )
        except TypeError:
            # 일부 토크나이저는 템플릿 인자를 허용하지 않는다.
            return tokenizer.apply_chat_template(raw, tokenize=False, add_generation_prompt=True)
    return "\n".join(f"{m.role}: {m.content}" for m in raw)


def _normalize_stop(stop: str | list[str] | None) -> list[str]:
    if stop is None:
        return []
    if isinstance(stop, str):
        return [stop] if stop else []
    return [s for s in stop if isinstance(s, str) and s]


def _apply_stop_sequences(text: str, stops: list[str]) -> tuple[str, bool]:
    if not text or not stops:
        return text, False

    cut_idx = -1
    for s in stops:
        idx = text.find(s)
        if idx == -1:
            continue
        if cut_idx == -1 or idx < cut_idx:
            cut_idx = idx

    if cut_idx == -1:
        return text, False
    return text[:cut_idx], True


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        _ensure_loaded()
        return {"status": "ok", "model": MODEL_ID, "device": DEVICE}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"loading failed: {exc}")


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_ID,
                "object": "model",
                "created": 0,
                "owned_by": "openvino",
            }
        ],
    }


@app.post("/v1/chat/completions")
def chat_completions(req: ChatCompletionRequest) -> dict[str, Any]:
    if req.stream:
        raise HTTPException(status_code=400, detail="stream=True is not supported by this OpenVINO server yet")

    tokenizer, model = _ensure_loaded()
    prompt = _messages_to_prompt(tokenizer, req.messages, req.chat_template_kwargs)
    inputs = tokenizer(prompt, return_tensors="pt")
    in_len = int(inputs["input_ids"].shape[-1])

    generate_kwargs: dict[str, Any] = {
        "max_new_tokens": req.max_tokens,
    }
    if req.temperature is not None and req.temperature > 0:
        generate_kwargs["do_sample"] = True
        generate_kwargs["temperature"] = req.temperature
        if req.top_p is not None:
            generate_kwargs["top_p"] = req.top_p
    else:
        generate_kwargs["do_sample"] = False

    t0 = time.time()
    output = model.generate(**inputs, **generate_kwargs)
    dt = max(time.time() - t0, 1e-9)

    out_ids = output[0]
    generated_ids = out_ids[in_len:]
    text = tokenizer.decode(generated_ids, skip_special_tokens=True)
    text, hit_stop = _apply_stop_sequences(text, _normalize_stop(req.stop))
    completion_tokens = int(len(generated_ids))
    finish_reason = "length" if completion_tokens >= req.max_tokens else "stop"
    if hit_stop:
        finish_reason = "stop"

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": in_len,
            "completion_tokens": completion_tokens,
            "total_tokens": in_len + completion_tokens,
        },
        "timings": {
            "predicted_per_second": completion_tokens / dt,
            "predicted_ms": dt * 1000.0,
        },
    }
