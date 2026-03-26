#!/usr/bin/env python3
"""Minimal IPEX-LLM GGUF smoke test."""

from __future__ import annotations

import argparse
import importlib.metadata
import sys

import torch
from ipex_llm.transformers import AutoModelForCausalLM


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GGUF model with IPEX-LLM")
    parser.add_argument(
        "--model-path",
        default="/home/dlckdgn/ai-models/qwen3.5-9b-null-space-abliterated-q6_k.gguf",
        help="Path to GGUF file",
    )
    parser.add_argument(
        "--prompt",
        default="한국어로 한 문장만 답해: 라멘의 매력을 알려줘.",
        help="Prompt for generation",
    )
    parser.add_argument(
        "--low-bit",
        default="sym_int4",
        help="IPEX-LLM low bit option used by from_gguf",
    )
    parser.add_argument("--max-new-tokens", type=int, default=64)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print(f"ipex-llm={importlib.metadata.version('ipex-llm')}")
    print(f"torch={torch.__version__}")
    print(f"xpu_available={torch.xpu.is_available()}")
    print(f"model_path={args.model_path}")

    try:
        model, tokenizer = AutoModelForCausalLM.from_gguf(
            args.model_path, low_bit=args.low_bit
        )
    except Exception as exc:
        print(f"[ERROR] from_gguf failed: {type(exc).__name__}: {exc}")
        print(
            "[HINT] Current IPEX-LLM GGUF loader may not support this model family "
            "or quant type. Try HF checkpoint path instead of GGUF."
        )
        return 2

    device = "xpu" if torch.xpu.is_available() else "cpu"
    model = model.to(device)
    print(f"device={device}")

    if hasattr(tokenizer, "apply_chat_template"):
        messages = [{"role": "user", "content": args.prompt}]
        input_ids = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt"
        ).to(device)
    else:
        input_ids = tokenizer.encode(args.prompt, return_tensors="pt").to(device)

    with torch.inference_mode():
        output = model.generate(
            input_ids,
            max_new_tokens=args.max_new_tokens,
            do_sample=True,
            temperature=0.2,
            top_p=0.9,
        )
    text = tokenizer.decode(output[0], skip_special_tokens=True)
    print("----- output -----")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
