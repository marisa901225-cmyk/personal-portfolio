from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Iterator

import httpx

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.rate_limit import rate_limit
from ..services.prompt_loader import load_prompt
from ..services.memory_service import search_memories
from ..services.llm_service import LLMService

router = APIRouter(prefix="/api/memories", tags=["Memories"], dependencies=[Depends(verify_api_token)])
logger = logging.getLogger(__name__)

DEFAULT_FALLBACK_MESSAGE = (
    "미안해요, 자기야. 답변을 생각하다 깜빡 졸았나 봐요. "
    "로컬 서버나 AI 설정이 괜찮은지 확인해줄래요? 😅"
)

LLM_LIGHT_BASE_URL = os.getenv("LLM_LIGHT_BASE_URL", "http://llama-server-light:8081")
LLM_LIGHT_MODEL_ID = os.getenv("LLM_LIGHT_MODEL_ID")

SUMMARY_CONTEXT_TOKENS = int(os.getenv("MEMORY_CHAT_CONTEXT_TOKENS", "4096"))
SUMMARY_TRIGGER_RATIO = float(os.getenv("MEMORY_CHAT_SUMMARY_TRIGGER_RATIO", "0.65"))
SUMMARY_TRIGGER_TOKENS = int(
    os.getenv(
        "MEMORY_CHAT_SUMMARY_TRIGGER_TOKENS",
        str(int(SUMMARY_CONTEXT_TOKENS * SUMMARY_TRIGGER_RATIO)),
    )
)
SUMMARY_KEEP_MESSAGES = int(os.getenv("MEMORY_CHAT_SUMMARY_KEEP_MESSAGES", "6"))
SUMMARY_MAX_TOKENS = int(os.getenv("MEMORY_CHAT_SUMMARY_MAX_TOKENS", "256"))
SUMMARY_SESSION_TTL_SEC = int(os.getenv("MEMORY_CHAT_SUMMARY_SESSION_TTL_SEC", "21600"))
DB_KEYWORDS_ENV = os.getenv("MEMORY_CHAT_DB_KEYWORDS", "")
_DEFAULT_DB_KEYWORDS = [
    "포트폴리오", "포폴", "자산", "수익률", "수익", "손익", "손실", "익절", "손절",
    "매수", "매도", "매매", "거래", "투자", "보유", "비중", "리밸런싱",
    "지출", "소비", "입금", "출금", "현금흐름", "배당", "세금", "카테고리",
    "예산", "뉴스", "리포트", "보고서", "요약",
    "스팀", "steam", "게임", "랭킹", "순위", "트렌드",
    "portfolio", "asset", "holding", "holdings", "return", "pnl", "profit", "loss",
    "trade", "buy", "sell", "expense", "spend", "income", "cashflow", "dividend",
    "report", "summary", "db", "duckdb", "sqlite",
]
DB_KEYWORDS = (
    [kw.strip() for kw in DB_KEYWORDS_ENV.split(",") if kw.strip()]
    if DB_KEYWORDS_ENV
    else _DEFAULT_DB_KEYWORDS
)

_light_client = httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))
_light_model_id_cache: Optional[str] = None


@dataclass
class SummaryState:
    summary: str = ""
    summarized_messages: int = 0
    updated_at: float = 0.0


_summary_state: dict[str, SummaryState] = {}
_summary_lock = threading.Lock()


def _get_light_model_id() -> str:
    global _light_model_id_cache
    if LLM_LIGHT_MODEL_ID:
        return LLM_LIGHT_MODEL_ID
    if _light_model_id_cache:
        return _light_model_id_cache
    try:
        url = f"{LLM_LIGHT_BASE_URL.rstrip('/')}/v1/models"
        response = _light_client.get(url)
        response.raise_for_status()
        data = response.json()
        items = data.get("data") or []
        if items and isinstance(items[0], dict):
            _light_model_id_cache = items[0].get("id", "Qwen3-0.6B")
            return _light_model_id_cache
    except Exception as exc:
        logger.warning("Light LLM model id lookup failed: %s", exc)
    return "Qwen3-0.6B"


def _generate_with_light_llm(messages: List[dict], max_tokens: int) -> str:
    try:
        url = f"{LLM_LIGHT_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": _get_light_model_id(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "top_p": 0.8,
            "top_k": 20,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = _light_client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("Light LLM summary call failed: %s", exc)
        return ""


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    non_ascii = len(text) - ascii_count
    return max(1, int(ascii_count / 4 + non_ascii / 2))


def _estimate_messages_tokens(messages: List[dict]) -> int:
    total = 0
    for msg in messages:
        total += _estimate_text_tokens(str(msg.get("content", "")))
        total += 4
    return total


def _format_messages_for_summary(messages: List[dict]) -> str:
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _format_number(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if digits == 0:
        return f"{num:,.0f}"
    return f"{num:,.{digits}f}"


def _needs_db_context(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    for kw in DB_KEYWORDS:
        if kw and kw.lower() in lowered:
            return True
    return False


def _build_db_context(query_text: str = "") -> str:
    try:
        from ..services.duckdb_refine import refine_portfolio_for_ai
        from ..services.news.refiner import refine_game_trends_with_duckdb, refine_economy_news_with_duckdb
        
        refined = refine_portfolio_for_ai()
    except Exception as exc:
        logger.warning("DB context build failed: %s", exc)
        return ""

    period = refined.get("period") or {}
    summary = refined.get("portfolio_summary") or {}
    benchmark = refined.get("benchmark") or {}
    assets = refined.get("asset_analytics") or []
    spending = refined.get("spending_by_category") or []

    lines: List[str] = []
    period_label = period.get("label")
    if period_label:
        lines.append(f"기간: {period_label}")

    total_value = summary.get("total_value")
    total_invested = summary.get("total_invested")
    total_unrealized = summary.get("total_unrealized_profit")
    if summary:
        lines.append(
            "총자산: {total} / 원금: {invested} / 미실현손익: {pnl}".format(
                total=_format_number(total_value),
                invested=_format_number(total_invested),
                pnl=_format_number(total_unrealized),
            )
        )

    portfolio_return = benchmark.get("portfolio_return_pct")
    benchmark_return = benchmark.get("return_pct")
    if portfolio_return is not None or benchmark_return is not None:
        lines.append(
            "수익률: {portfolio}% (벤치마크 {benchmark}%)".format(
                portfolio=_format_number(portfolio_return, 2),
                benchmark=_format_number(benchmark_return, 2),
            )
        )

    top_assets: List[str] = []
    for asset in assets[:3]:
        name = asset.get("name") or asset.get("ticker") or "N/A"
        ticker = asset.get("ticker")
        label = name
        if ticker and ticker not in name:
            label = f"{name}({ticker})"
        value_text = _format_number(asset.get("current_value"))
        return_text = _format_number(asset.get("return_pct"), 2)
        top_assets.append(f"{label}: {value_text}, {return_text}%")
    if top_assets:
        lines.append("상위 자산: " + " | ".join(top_assets))

    top_spending: List[str] = []
    for row in spending[:3]:
        category = row.get("category") or "기타"
        amount = row.get("total_amount")
        top_spending.append(f"{category} {_format_number(amount)}")
    if top_spending:
        lines.append("지출 상위: " + " | ".join(top_spending))

    # Steam/Game 트렌드 및 뉴스 추가 (LO의 요청 💖)
    q = query_text.lower()
    if any(kw in q for kw in ["스팀", "steam", "게임", "랭킹", "순위", "트렌드"]):
        lines.append("\n[Steam 게임 트렌드/랭킹]")
        game_trends = refine_game_trends_with_duckdb(query_text)
        lines.append(game_trends)
    
    # 일반 뉴스/경제 컨텍스트 추가
    if any(kw in q for kw in ["뉴스", "경제", "시황", "리포트"]):
        lines.append("\n[경제/시장 뉴스 요약]")
        econ_news = refine_economy_news_with_duckdb(query_text)
        lines.append(econ_news)

    return "\n".join(lines)


def _summarize_messages(existing_summary: str, messages: List[dict]) -> Optional[str]:
    if not messages:
        return None

    messages_text = _format_messages_for_summary(messages)
    prompt = load_prompt(
        "memory_chat_summary",
        summary_text=existing_summary or "없음",
        messages_text=messages_text,
    )
    if not prompt.strip():
        return None

    summary = _generate_with_light_llm([{"role": "user", "content": prompt}], SUMMARY_MAX_TOKENS)
    if summary:
        return summary

    llm = LLMService.get_instance()
    fallback = llm.generate_chat(
        [{"role": "user", "content": prompt}],
        max_tokens=SUMMARY_MAX_TOKENS,
        temperature=0.2,
        top_p=0.8,
        top_k=20,
        stop=None,
    )
    return fallback or None


def _cleanup_summary_state(now_ts: float) -> None:
    if SUMMARY_SESSION_TTL_SEC <= 0:
        return
    with _summary_lock:
        stale_keys = [
            key for key, state in _summary_state.items()
            if now_ts - state.updated_at > SUMMARY_SESSION_TTL_SEC
        ]
        for key in stale_keys:
            _summary_state.pop(key, None)


def _prepare_chat_context(session_id: str, messages: List[dict]) -> tuple[str, List[dict]]:
    now_ts = time.time()
    _cleanup_summary_state(now_ts)

    with _summary_lock:
        state = _summary_state.get(session_id, SummaryState())

    if state.summarized_messages > len(messages):
        state = SummaryState()

    summarized_count = state.summarized_messages
    unsummarized = messages[summarized_count:]

    estimated_tokens = _estimate_text_tokens(state.summary) + _estimate_messages_tokens(unsummarized)
    if estimated_tokens > SUMMARY_TRIGGER_TOKENS and len(unsummarized) > SUMMARY_KEEP_MESSAGES:
        to_summarize = unsummarized[:-SUMMARY_KEEP_MESSAGES]
        new_summary = _summarize_messages(state.summary, to_summarize)
        if new_summary is not None:
            state.summary = new_summary
            summarized_count += len(to_summarize)
            unsummarized = messages[summarized_count:]

    state.summarized_messages = summarized_count
    state.updated_at = now_ts

    with _summary_lock:
        _summary_state[session_id] = state

    return state.summary, unsummarized


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    max_tokens: int = 1024
    session_id: Optional[str] = None


def chat_stream_generator(
    messages: List[dict],
    memories_text: str,
    summary_text: str,
    db_context: str,
    model: Optional[str],
    max_tokens: int = 1024,
) -> Iterator[str]:
    try:
        llm = LLMService.get_instance()

        # 외부 파일에서 프롬프트 로드 (LO의 요청에 따라 하드코딩 제거)
        system_prompt = load_prompt(
            "memory_chat",
            memories_text=memories_text or "현재 저장된 장기 기억이 없습니다.",
            summary_text=summary_text or "대화 요약이 없습니다.",
            db_context=db_context or "DB 요약이 없습니다.",
        )

        api_messages = [{"role": "system", "content": system_prompt}] + messages

        # 로컬 모델 우선 사용 (generate_chat은 원격 llama-server를 먼저 시도하고 실패 시 폴백함)
        response_text = llm.generate_chat(
            api_messages,
            model=model,
            max_tokens=max_tokens,
        )

        if response_text:
            yield response_text
            return

        last_error = llm.get_last_error()
        if last_error:
            logger.warning("Memory chat empty response: %s", last_error)

        yield DEFAULT_FALLBACK_MESSAGE
    except Exception:
        logger.exception("Memory chat stream failed")
        yield DEFAULT_FALLBACK_MESSAGE


@router.post("/chat")
def memory_chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(rate_limit(limit=20, window_sec=60, key_prefix="memory_chat")),
):
    """AI 장기기억 대화방 엔드포인트"""
    try:
        session_id = req.session_id or "default"
        # 최신 메시지 기반으로 관련 기억 검색
        last_user_msg = next((m.content for m in reversed(req.messages) if m.role == "user"), "")
        try:
            memories = search_memories(db, user_id=1, query=last_user_msg, limit=10)
        except Exception:
            logger.exception("Memory search failed; continuing without memories")
            memories = []

        memories_text = ""
        if memories:
            cat_map = {}
            for m in memories:
                if m.category not in cat_map:
                    cat_map[m.category] = []
                cat_map[m.category].append(m.content)

            lines = []
            for cat, m_list in cat_map.items():
                lines.append(f"• {cat.upper()}:")
                for content in m_list:
                    lines.append(f"  - {content}")
            memories_text = "\n".join(lines)

        # API 메시지 형식으로 변환
        api_messages = [m.model_dump() for m in req.messages]
        summary_text, trimmed_messages = _prepare_chat_context(session_id, api_messages)

        db_context = ""
        if _needs_db_context(last_user_msg):
            db_context = _build_db_context(last_user_msg)

        return StreamingResponse(
            chat_stream_generator(
                trimmed_messages,
                memories_text,
                summary_text,
                db_context,
                req.model,
                req.max_tokens,
            ),
            media_type="text/plain; charset=utf-8",
        )
    except Exception:
        logger.exception("Memory chat failed")

        def fallback() -> Iterator[str]:
            yield DEFAULT_FALLBACK_MESSAGE

        return StreamingResponse(
            fallback(),
            media_type="text/plain; charset=utf-8",
        )
