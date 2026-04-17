from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any

import requests

from ..alarm.sanitizer import clean_exaone_tokens
from ..prompt_loader import load_prompt
from .config import TradeEngineConfig
from .risk import _is_in_window
from .utils import parse_numeric

logger = logging.getLogger(__name__)
_SWING_SKIP_LLM_TIMEOUT_SEC = 4.0
_SWING_SKIP_LLM_MAX_TOKENS = 80


def maybe_build_candidate_notification(
    *,
    now: datetime,
    candidates: Any,
    regime: str,
    config: TradeEngineConfig,
    last_notified_window_idx: int | None,
    display_candidates: Any | None = None,
) -> tuple[int | None, str | None]:
    if candidates.merged.empty:
        return last_notified_window_idx, None

    current_window_idx = _current_entry_window_idx(now, config)
    if current_window_idx is None:
        return last_notified_window_idx, None
    if last_notified_window_idx == current_window_idx:
        return last_notified_window_idx, None

    candidate_rows = display_candidates if display_candidates is not None else candidates.merged
    if candidate_rows is None or getattr(candidate_rows, "empty", True):
        candidate_rows = candidates.merged
    top_10 = candidate_rows.head(10)
    lines = [f"🎯 [Entry Window] Scanned Symbols ({regime})"]
    if regime == "RISK_OFF":
        lines.append("※ RISK_OFF 상태: 후보 관찰 전용 (공격적 신규 진입 차단)")
        if config.risk_off_parking_enabled and config.risk_off_parking_code:
            lines.append(f"※ 여유 현금 파킹 대상: {config.risk_off_parking_code}")
    for i, (_, row) in enumerate(top_10.iterrows(), 1):
        code = row["code"]
        name = row["name"]
        val5 = parse_numeric(row.get("avg_value_5d")) or 0
        val20 = parse_numeric(row.get("avg_value_20d")) or 0
        val = max(val5, val20)
        lines.append(f"{i}. {name}({code}) | {val/1e8:.1f}억")

    return current_window_idx, "\n".join(lines)


def maybe_build_swing_skip_notification(
    *,
    now: datetime,
    trade_date: str,
    regime: str,
    config: TradeEngineConfig,
    last_notified_window_idx: int | None,
    reason: str,
    model_count: int,
    etf_count: int,
) -> tuple[int | None, str | None]:
    current_window_idx = _current_entry_window_idx(now, config)
    if current_window_idx is None:
        return last_notified_window_idx, None
    if last_notified_window_idx == current_window_idx:
        return last_notified_window_idx, None

    start, end = config.entry_windows[current_window_idx]
    window_label = f"{start}-{end}"
    next_window_label = _next_window_label(current_window_idx, config)

    if reason == "NO_SWING_PICK":
        lead = f"{window_label} 창은 후보를 끝까지 못 좁혀서 스윙 매수는 쉬어갔어."
    else:
        lead = f"{window_label} 창은 스윙 후보가 안 보여서 매수는 쉬어갔어."

    if next_window_label:
        tail = f" {next_window_label} 창에서 다시 볼게."
    else:
        tail = " 오늘은 무리해서 안 들어갈게."

    fallback_message = f"[SWING][SKIP] {lead}{tail}"
    message = _rewrite_swing_skip_message(
        fallback_message=fallback_message,
        reason=reason,
        regime=regime,
        trade_date=trade_date,
        window_label=window_label,
        next_window_label=next_window_label,
        model_count=model_count,
        etf_count=etf_count,
    )
    return current_window_idx, message


def _current_entry_window_idx(now: datetime, config: TradeEngineConfig) -> int | None:
    for i, (start, end) in enumerate(config.entry_windows):
        if _is_in_window(now, start, end):
            return i
    return None


def _next_window_label(current_window_idx: int, config: TradeEngineConfig) -> str | None:
    next_window_idx = current_window_idx + 1
    if next_window_idx >= len(config.entry_windows):
        return None
    start, end = config.entry_windows[next_window_idx]
    return f"{start}-{end}"


def _rewrite_swing_skip_message(
    *,
    fallback_message: str,
    reason: str,
    regime: str,
    trade_date: str,
    window_label: str,
    next_window_label: str | None,
    model_count: int,
    etf_count: int,
) -> str:
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    if not base_url:
        return fallback_message

    prompt = load_prompt(
        "trading_swing_skip_message",
        fallback_message=fallback_message,
        reason=reason,
        regime=regime,
        trade_date=trade_date,
        window_label=window_label,
        next_window_label=next_window_label or "없음",
        model_count=model_count,
        etf_count=etf_count,
    )
    if not prompt:
        return fallback_message

    headers = {"Content-Type": "application/json"}
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": os.getenv("LLM_REMOTE_DEFAULT_MODEL", "").strip() or "local-model",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": _SWING_SKIP_LLM_MAX_TOKENS,
        "temperature": 0.3,
        "top_p": 0.9,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    timeout_raw = os.getenv("LLM_TIMEOUT", "120").strip() or "120"
    try:
        timeout_sec = min(float(timeout_raw), _SWING_SKIP_LLM_TIMEOUT_SEC)
    except ValueError:
        timeout_sec = _SWING_SKIP_LLM_TIMEOUT_SEC

    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout_sec,
        )
        response.raise_for_status()
        data = response.json()
        raw_text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        normalized = _normalize_swing_skip_message(raw_text)
        if not normalized:
            return fallback_message
        if not normalized.startswith("[SWING][SKIP]"):
            normalized = f"[SWING][SKIP] {normalized}"
        return normalized
    except Exception as exc:
        logger.info("swing skip LLM rewrite fallback: %s", exc)
        return fallback_message


def _normalize_swing_skip_message(raw_text: str) -> str:
    cleaned = clean_exaone_tokens(raw_text or "").strip().strip("\"'")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 12:
        return ""
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
        if " " in cleaned:
            cleaned = cleaned.rsplit(" ", 1)[0]
        cleaned = cleaned.rstrip(".,! ") + "."
    return cleaned
