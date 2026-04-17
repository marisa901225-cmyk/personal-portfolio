from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any

import pandas as pd
import requests

from ..alarm.sanitizer import clean_exaone_tokens
from ..prompt_loader import load_prompt
from .config import TradeEngineConfig
from .risk import _is_in_window
from .utils import parse_numeric

logger = logging.getLogger(__name__)
_SWING_SKIP_LLM_TIMEOUT_SEC = 4.0
_SWING_SKIP_LLM_MAX_TOKENS = 80


def maybe_build_candidate_notifications(
    *,
    now: datetime,
    candidates: Any,
    regime: str,
    config: TradeEngineConfig,
    last_notified_window_idx: int | None,
    display_candidates: Any | None = None,
) -> tuple[int | None, list[str]]:
    merged = getattr(candidates, "merged", None)
    if merged is None or getattr(merged, "empty", True):
        return last_notified_window_idx, []

    current_window_idx = _current_entry_window_idx(now, config)
    if current_window_idx is None:
        return last_notified_window_idx, []
    if last_notified_window_idx == current_window_idx:
        return last_notified_window_idx, []

    day_rows = _resolve_day_notification_rows(candidates=candidates, display_candidates=display_candidates)
    swing_rows = _resolve_swing_notification_rows(candidates=candidates)

    messages: list[str] = []
    if swing_rows is not None and not getattr(swing_rows, "empty", True):
        messages.append(
            _build_candidate_notification_text(
                candidate_rows=swing_rows,
                regime=regime,
                config=config,
                strategy_label="SWING",
                icon="📈",
            )
        )
    if day_rows is not None and not getattr(day_rows, "empty", True):
        messages.append(
            _build_candidate_notification_text(
                candidate_rows=day_rows,
                regime=regime,
                config=config,
                strategy_label="DAY",
                icon="⚡",
            )
        )

    if messages:
        return current_window_idx, messages

    fallback_rows = display_candidates if display_candidates is not None else merged
    if fallback_rows is None or getattr(fallback_rows, "empty", True):
        fallback_rows = merged
    if fallback_rows is None or getattr(fallback_rows, "empty", True):
        return current_window_idx, []

    return current_window_idx, [
        _build_candidate_notification_text(
            candidate_rows=fallback_rows,
            regime=regime,
            config=config,
            strategy_label=None,
            icon="🎯",
        )
    ]


def maybe_build_candidate_notification(
    *,
    now: datetime,
    candidates: Any,
    regime: str,
    config: TradeEngineConfig,
    last_notified_window_idx: int | None,
    display_candidates: Any | None = None,
) -> tuple[int | None, str | None]:
    updated_idx, messages = maybe_build_candidate_notifications(
        now=now,
        candidates=candidates,
        regime=regime,
        config=config,
        last_notified_window_idx=last_notified_window_idx,
        display_candidates=display_candidates,
    )
    if not messages:
        return updated_idx, None
    return updated_idx, "\n\n".join(messages)


def _resolve_day_notification_rows(*, candidates: Any, display_candidates: Any | None) -> Any | None:
    if display_candidates is not None and not getattr(display_candidates, "empty", True):
        return display_candidates
    popular = getattr(candidates, "popular", None)
    if popular is not None and not getattr(popular, "empty", True):
        return popular
    return None


def _resolve_swing_notification_rows(*, candidates: Any) -> Any | None:
    model = getattr(candidates, "model", None)
    etf = getattr(candidates, "etf", None)

    model_empty = model is None or getattr(model, "empty", True)
    etf_empty = etf is None or getattr(etf, "empty", True)

    if model_empty and etf_empty:
        return None
    if model_empty:
        return etf
    if etf_empty:
        return model

    if "code" not in model.columns or "code" not in etf.columns:
        return model

    seen_codes = {str(code) for code in model["code"].astype(str).tolist()}
    etf_only = etf[~etf["code"].astype(str).isin(seen_codes)]
    if etf_only.empty:
        return model
    return _concat_rows([model, etf_only])


def _concat_rows(frames: list[Any]) -> Any | None:
    valid_frames = [frame for frame in frames if frame is not None and not getattr(frame, "empty", True)]
    if not valid_frames:
        return None
    if len(valid_frames) == 1:
        return valid_frames[0]
    return pd.concat(valid_frames, ignore_index=True)


def _build_candidate_notification_text(
    *,
    candidate_rows: Any,
    regime: str,
    config: TradeEngineConfig,
    strategy_label: str | None,
    icon: str,
) -> str:
    top_10 = candidate_rows.head(10)
    label_suffix = f"[{strategy_label}] " if strategy_label else ""
    lines = [f"{icon} [Entry Window] {label_suffix}Scanned Symbols ({regime})"]
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
    return "\n".join(lines)


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
