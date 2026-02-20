from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Iterator

import httpx

from .prompt_loader import load_prompt
from .llm_service import LLMService

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

def get_light_model_id() -> str:
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

def generate_with_light_llm(messages: List[dict], max_tokens: int) -> str:
    try:
        url = f"{LLM_LIGHT_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": get_light_model_id(),
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

def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_count = sum(1 for ch in text if ord(ch) < 128)
    non_ascii = len(text) - ascii_count
    return max(1, int(ascii_count / 4 + non_ascii / 2))

def estimate_messages_tokens(messages: List[dict]) -> int:
    total = 0
    for msg in messages:
        total += estimate_text_tokens(str(msg.get("content", "")))
        total += 4
    return total

def format_messages_for_summary(messages: List[dict]) -> str:
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines)

def format_number(value: Optional[float], digits: int = 0) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    if digits == 0:
        return f"{num:,.0f}"
    return f"{num:,.{digits}f}"

def needs_db_context(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    for kw in DB_KEYWORDS:
        if kw and kw.lower() in lowered:
            return True
    return False

def build_db_context(query_text: str = "") -> str:
    try:
        from .duckdb_refine import refine_portfolio_for_ai
        from .news.refiner import refine_game_trends_with_duckdb, refine_economy_news_with_duckdb
        
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
                total=format_number(total_value),
                invested=format_number(total_invested),
                pnl=format_number(total_unrealized),
            )
        )

    portfolio_return = benchmark.get("portfolio_return_pct")
    benchmark_return = benchmark.get("return_pct")
    if portfolio_return is not None or benchmark_return is not None:
        lines.append(
            "수익률: {portfolio}% (벤치마크 {benchmark}%)".format(
                portfolio=format_number(portfolio_return, 2),
                benchmark=format_number(benchmark_return, 2),
            )
        )

    top_assets: List[str] = []
    for asset in assets[:3]:
        name = asset.get("name") or asset.get("ticker") or "N/A"
        ticker = asset.get("ticker")
        label = name
        if ticker and ticker not in name:
            label = f"{name}({ticker})"
        value_text = format_number(asset.get("current_value"))
        return_text = format_number(asset.get("return_pct"), 2)
        top_assets.append(f"{label}: {value_text}, {return_text}%")
    if top_assets:
        lines.append("상위 자산: " + " | ".join(top_assets))

    top_spending: List[str] = []
    for row in spending[:3]:
        category = row.get("category") or "기타"
        amount = row.get("total_amount")
        top_spending.append(f"{category} {format_number(amount)}")
    if top_spending:
        lines.append("지출 상위: " + " | ".join(top_spending))

    q = query_text.lower()
    if any(kw in q for kw in ["스팀", "steam", "게임", "랭킹", "순위", "트렌드"]):
        lines.append("\n[Steam 게임 트렌드/랭킹]")
        game_trends = refine_game_trends_with_duckdb(query_text)
        lines.append(game_trends)
    
    if any(kw in q for kw in ["뉴스", "경제", "시황", "리포트"]):
        lines.append("\n[경제/시장 뉴스 요약]")
        econ_news = refine_economy_news_with_duckdb(query_text)
        lines.append(econ_news)

    return "\n".join(lines)

def summarize_messages(existing_summary: str, messages: List[dict]) -> Optional[str]:
    if not messages:
        return None

    messages_text = format_messages_for_summary(messages)
    prompt = load_prompt(
        "memory_chat_summary",
        summary_text=existing_summary or "없음",
        messages_text=messages_text,
    )
    if not prompt.strip():
        return None

    summary = generate_with_light_llm([{"role": "user", "content": prompt}], SUMMARY_MAX_TOKENS)
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

def cleanup_summary_state(now_ts: float) -> None:
    if SUMMARY_SESSION_TTL_SEC <= 0:
        return
    with _summary_lock:
        stale_keys = [
            key for key, state in _summary_state.items()
            if now_ts - state.updated_at > SUMMARY_SESSION_TTL_SEC
        ]
        for key in stale_keys:
            _summary_state.pop(key, None)

def prepare_chat_context(session_id: str, messages: List[dict]) -> tuple[str, List[dict]]:
    now_ts = time.time()
    cleanup_summary_state(now_ts)

    with _summary_lock:
        state = _summary_state.get(session_id, SummaryState())

    if state.summarized_messages > len(messages):
        state = SummaryState()

    summarized_count = state.summarized_messages
    unsummarized = messages[summarized_count:]

    estimated_tokens = estimate_text_tokens(state.summary) + estimate_messages_tokens(unsummarized)
    if estimated_tokens > SUMMARY_TRIGGER_TOKENS and len(unsummarized) > SUMMARY_KEEP_MESSAGES:
        to_summarize = unsummarized[:-SUMMARY_KEEP_MESSAGES]
        new_summary = summarize_messages(state.summary, to_summarize)
        if new_summary is not None:
            state.summary = new_summary
            summarized_count += len(to_summarize)
            unsummarized = messages[summarized_count:]

    state.summarized_messages = summarized_count
    state.updated_at = now_ts

    with _summary_lock:
        _summary_state[session_id] = state

    return state.summary, unsummarized

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

        system_prompt = load_prompt(
            "memory_chat",
            memories_text=memories_text or "현재 저장된 장기 기억이 없습니다.",
            summary_text=summary_text or "대화 요약이 없습니다.",
            db_context=db_context or "DB 요약이 없습니다.",
        )

        api_messages = [{"role": "system", "content": system_prompt}] + messages

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
