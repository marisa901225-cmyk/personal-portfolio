# backend/services/alarm/llm_refiner.py
import asyncio
import httpx
import logging
import os
import re
import json
from datetime import datetime
from typing import List, Optional

from .sanitizer import clean_exaone_tokens
from ..prompt_loader import load_prompt
from ..llm_service import LLMService

logger = logging.getLogger(__name__)

# 2차 정제용 경량 LLM 서버 URL
LLM_LIGHT_BASE_URL = os.getenv("LLM_LIGHT_BASE_URL", "http://llama-server-light:8081")

# LLM 초안 디버그 로깅 (환경변수로 제어)
DEBUG_LLM_DRAFT = os.getenv("DEBUG_LLM_DRAFT", "0") == "1"
LLM_DRAFT_LOG_PATH = os.getenv(
    "LLM_DRAFT_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "../../data/llm_drafts.jsonl")
)
LLM_DRAFT_LOG_MAX_MB = int(os.getenv("LLM_DRAFT_LOG_MAX_MB", "10"))

# LLM stop 토큰 (공통 지시사항)
STOP_TOKENS = ["Okay", "let me", "Let me", "I'll", "사용자가", "지시사항을", "지문을", "지시를", "알겠습니다", "확인했습니다", "요청하신 대로", "아래는"]

# Light LLM 클라이언트 재사용
_light_async_client = None
_light_model_id_cache = None


def _get_light_client() -> httpx.AsyncClient:
    """Light LLM httpx AsyncClient를 재사용한다."""
    global _light_async_client
    if _light_async_client is None:
        _light_async_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=5.0)
        )
    return _light_async_client


async def close_light_client():
    """애플리케이션 종료 시 AsyncClient를 닫는다."""
    global _light_async_client
    if _light_async_client is not None:
        logger.info("Closing Light LLM AsyncClient...")
        await _light_async_client.aclose()
        _light_async_client = None


async def _get_light_model_id() -> str:
    """Light LLM 서버의 모델 ID를 가져온다 (env 우선, /v1/models 조회 fallback)."""
    global _light_model_id_cache
    
    env_model = os.getenv("LLM_LIGHT_MODEL_ID")
    if env_model:
        return env_model
    
    if _light_model_id_cache:
        return _light_model_id_cache
    
    try:
        client = _get_light_client()
        url = f"{LLM_LIGHT_BASE_URL.rstrip('/')}/v1/models"
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        items = data.get("data") or []
        if items and isinstance(items[0], dict):
            model_id = items[0].get("id", "Qwen3-0.6B")
            _light_model_id_cache = model_id
            logger.info(f"Light LLM model ID detected: {model_id}")
            return model_id
    except Exception as e:
        logger.warning(f"Failed to get light model id: {e}")
    
    return "Qwen3-0.6B"


def dump_llm_draft(tag: str, draft: str):
    """LLM 1차 출력(draft)만 파일로 남긴다 (디버그용)."""
    if not DEBUG_LLM_DRAFT or not draft:
        return

    try:
        from pathlib import Path
        p = Path(LLM_DRAFT_LOG_PATH).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)

        if p.exists() and p.stat().st_size / (1024 * 1024) >= LLM_DRAFT_LOG_MAX_MB:
            rotated = p.with_suffix(p.suffix + ".1")
            if rotated.exists(): rotated.unlink()
            p.rename(rotated)

        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tag": tag,
            "len": len(draft),
            "draft": draft,
        }
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        try:
            os.chmod(str(p), 0o600)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Failed to dump llm draft: {e}")


def clean_meta_headers(text: str) -> str:
    """LLM 출력에서 '주제:', '출력 예:' 등의 메타 헤더를 제거한다."""
    if not text:
        return text
    
    meta_patterns = [
        r'^\s*(주제|Topic|테마)[:\s]+.*?\n',
        r'^\s*(출력\s*예?|Example\s*Output?|Output)[:\s]+.*?\n',
        r'^\s*\[?Draft\]?[:\s]*',
        r'^\s*---+\s*\n',
    ]
    
    result = text
    for pattern in meta_patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE | re.MULTILINE)
    
    return result.strip()


async def generate_with_main_llm_async(
    messages: List[dict],
    *,
    max_tokens: int,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    stop: List[str] | None = None,
    enable_thinking: bool | None = None,
    model: str | None = None,
) -> str:
    """메인 LLM 호출을 asyncio.to_thread로 감싸 비동기 이벤트 루프 블로킹을 방지한다."""
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        return ""
    
    kwargs = {}
    if top_p is not None: kwargs["top_p"] = top_p
    if top_k is not None: kwargs["top_k"] = top_k
    if enable_thinking is not None: kwargs["enable_thinking"] = enable_thinking
    if model is not None: kwargs["model"] = model

    return await asyncio.to_thread(
        llm_service.generate_chat,
        messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=stop,
        **kwargs
    )


async def generate_with_light_llm_async(
    messages: List[dict],
    max_tokens: int = 256,
    temperature: float = 0.3,
    top_p: float = 0.8,
    top_k: int = 20
) -> str:
    """경량 LLM 서버를 사용하여 비동기로 텍스트를 생성한다."""
    try:
        client = _get_light_client()
        url = f"{LLM_LIGHT_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": await _get_light_model_id(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Light LLM call failed, falling back to main LLM: {e}")
        return await generate_with_main_llm_async(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            stop=STOP_TOKENS,
            enable_thinking=False  # 정제 작업은 thinking 불필요
        )


async def refine_draft_with_light_llm_async(
    *,
    prompt_key: str,
    draft: str,
    max_tokens: int = 256,
    temperature: float = 0.3,
    dump_tag: str | None = None,
    clean_meta: bool = True,
    **prompt_kwargs
) -> str:
    """2차 정제 엔진: 호출, 로깅, 폴백, 후처리를 통합 관리한다."""
    if not draft or not draft.strip():
        return draft

    refine_prompt = load_prompt(prompt_key, draft=draft, **prompt_kwargs)
    if not refine_prompt:
        return draft

    refined = await generate_with_light_llm_async(
        [{"role": "user", "content": refine_prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    refined = clean_exaone_tokens(refined)

    if clean_meta:
        refined = clean_meta_headers(refined)

    if dump_tag:
        dump_llm_draft(dump_tag, refined)

    return refined.strip() or draft
