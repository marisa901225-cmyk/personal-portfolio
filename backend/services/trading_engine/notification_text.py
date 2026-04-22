from __future__ import annotations

from typing import Any

from .utils import parse_numeric


_STRATEGY_LABELS = {
    "DAY": "단타",
    "T": "단타",
    "SWING": "스윙",
    "S": "스윙",
    "P": "파킹",
}

_REGIME_LABELS = {
    "RISK_ON": "위험선호",
    "RISK_OFF": "위험회피",
    "N/A": "해당없음",
}

_REASON_LABELS = {
    "ALREADY_HELD_PROFITABLE": "기존 수익 포지션 보유 중",
    "BROKER_POSITION_MISSING": "브로커 계좌에서 포지션이 사라짐",
    "BROKER_POSITION_FOUND_DURING_POLLING_SYNC": "브로커 포지션을 폴링 중 발견",
    "BROKER_POSITION_FOUND_AFTER_ENTRY_ATTEMPT": "진입 재확인 중 브로커 포지션 확인",
    "BROKER_POSITION_MISMATCH": "브로커 수량/평단 불일치",
    "BROKER_SYNC": "브로커 동기화",
    "DAILY_MAX_LOSS": "일일 손실 한도 도달",
    "DAY_AFTERNOON_LOSS_LIMIT": "오후 단타 손실 제한",
    "DAY_ENTRY_FAILED": "단타 진입 실패",
    "DAY_LLM_VETO": "단타 LLM 검토 보류",
    "ENTRY_WINDOW_CLOSED": "진입 시간창 아님",
    "FETCH_FAILED": "장중 데이터 조회 실패",
    "FORCE": "장마감 강제청산",
    "HOLIDAY": "휴장일",
    "INTRADAY_RETRACE": "장중 고점 대비 되밀림",
    "LOCK": "수익보전 이탈",
    "MAX_CONSECUTIVE_LOSSES": "연속 손실 제한",
    "MAX_DAY_ENTRIES_DAY": "일일 단타 진입 횟수 제한",
    "MAX_DAY_POSITIONS": "단타 보유 수 제한",
    "MAX_SWING_ENTRIES_DAY": "일일 스윙 진입 횟수 제한",
    "MAX_SWING_ENTRIES_WEEK": "주간 스윙 진입 횟수 제한",
    "MAX_SWING_POSITIONS": "스윙 보유 수 제한",
    "MAX_TOTAL_POSITIONS": "총 보유 수 제한",
    "MOMENTUM_PULLBACK_OK": "강한 추세 눌림 허용",
    "NO_CANDIDATE": "후보 없음",
    "NO_DATA": "장중 데이터 없음",
    "NO_DAY_PICK": "단타 최종 후보 없음",
    "NO_NEW_ENTRY_AFTER": "신규 진입 마감 시간 이후",
    "NO_SWING_PICK": "스윙 최종 후보 없음",
    "PARKING_DISABLED": "파킹 비활성",
    "PARKING_ROTATE": "파킹 종목 교체",
    "PASS": "보류",
    "PENDING": "주문 대기",
    "RISK_OFF": "위험회피 장세",
    "RISK_ON": "위험선호 전환",
    "SL": "손절",
    "SL_TREND": "추세이탈 손절",
    "STATE_RECONCILE_ADD": "상태 동기화 신규 반영",
    "STATE_RECONCILE_DROP": "상태 동기화 정리",
    "STATE_RECONCILE_UPDATE": "상태 동기화 보정",
    "SWING_ENTRY_FAILED": "스윙 진입 실패",
    "SWING_LLM_VETO": "스윙 LLM 검토 보류",
    "TIME": "보유기간 만료",
    "TIGHT_INTRADAY_BASE": "강한 눌림목",
    "TP": "익절",
    "TRAIL": "추세 추적 청산",
    "UNKNOWN": "미확인",
    "UNSUPPORTED": "장중 확인 미지원",
    "WEAK_INTRADAY_LAST_BAR": "직전 봉 약세",
    "WEAK_INTRADAY_WINDOW": "최근 장중 흐름 약세",
}


def strategy_label(value: str) -> str:
    normalized = str(value or "").strip().upper()
    return _STRATEGY_LABELS.get(normalized, str(value or "전략"))


def regime_label(value: str) -> str:
    normalized = str(value or "").strip().upper()
    return _REGIME_LABELS.get(normalized, str(value or "미확인"))


def reason_label(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "미확인"
    return _REASON_LABELS.get(raw.upper(), raw)


def format_pass_message(reason: str, trade_date: str) -> str:
    return f"[보류] {reason_label(reason)} {trade_date}"


def format_run_start_message(trade_date: str) -> str:
    return f"[시작] 거래 엔진 시작 {trade_date}"


def format_error_message(trade_date: str, error_text: str) -> str:
    return f"[오류] {trade_date} {error_text}"


def format_chart_review_skip_message(
    *,
    strategy: str,
    reason: str,
    code: str | None = None,
) -> str:
    code_text = f" 종목={code}" if code else ""
    return f"[{strategy_label(strategy)}][LLM][보류] 검토 완료, 미진입 사유={reason_label(reason)}{code_text}"


def format_entry_message(
    *,
    strategy: str,
    code: str,
    qty: int,
    avg_price: float,
    regime: str,
    sync: bool = False,
) -> str:
    sync_text = "[동기화]" if sync else ""
    return (
        f"[진입][{strategy_label(strategy)}]{sync_text} {code} "
        f"수량={qty} 평균가={avg_price:.0f} 장세={regime_label(regime)}"
    )


def format_pending_entry_message(
    *,
    strategy: str,
    code: str,
    order_id: str,
    qty: int,
    remaining_qty: int,
    price: int,
) -> str:
    return (
        f"[진입대기][{strategy_label(strategy)}] {code} 주문번호={order_id or '없음'} "
        f"주문수량={qty} 잔여수량={remaining_qty} 주문가={price}"
    )


def format_exit_message(
    *,
    strategy: str,
    reason: str,
    code: str,
    qty: int,
    avg_price: float,
    pnl_pct: float,
) -> str:
    return (
        f"[청산][{strategy_label(strategy)}][{reason_label(reason)}] {code} "
        f"수량={qty} 평균가={avg_price:.0f} 손익={pnl_pct:+.2f}%"
    )


def format_candidate_review_message(
    *,
    strategy: str,
    shortlisted_codes: list[str],
    selected_code: str | None,
    approved_codes: list[str],
    summary: str,
) -> str:
    shortlist = ",".join(shortlisted_codes) or "없음"
    selected = selected_code or (approved_codes[0] if approved_codes else "없음")
    approved = ",".join(approved_codes) or "없음"
    return (
        f"[{strategy_label(strategy)}][LLM] 후보={shortlist} "
        f"선택={selected} 승인={approved} {summary}"
    )


def format_state_sync_add_message(
    *,
    code: str,
    strategy: str,
    qty: int,
    avg_price: float,
) -> str:
    return (
        f"[상태동기화][신규반영] {code} 전략={strategy_label(strategy)} "
        f"수량={qty} 평균가={avg_price:.0f} 기준=브로커"
    )


def format_state_sync_update_message(
    *,
    code: str,
    old_qty: int,
    new_qty: int,
    old_avg_price: float,
    new_avg_price: float,
) -> str:
    return (
        f"[상태동기화][보정] {code} "
        f"수량={old_qty}->{new_qty} 평균가={old_avg_price:.0f}->{new_avg_price:.0f}"
    )


def format_state_sync_drop_message(
    *,
    code: str,
    local_qty: int,
    last_price: float | None,
) -> str:
    parts = [f"[상태동기화][정리] {code} 로컬수량={local_qty} 브로커수량=0 기준=브로커계좌조회"]
    if last_price is not None:
        parts.append(f"마지막가={float(last_price):.0f}")
    return " ".join(parts)


def format_candidate_window_title(strategy_label_text: str | None, regime: str) -> str:
    prefix = f"[{strategy_label_text}] " if strategy_label_text else ""
    return f"{prefix}후보 종목 ({regime_label(regime)})"


def summarize_rows(candidate_rows: Any) -> list[str]:
    lines: list[str] = []
    for i, (_, row) in enumerate(candidate_rows.head(10).iterrows(), 1):
        code = row["code"]
        name = row["name"]
        val5 = parse_numeric(row.get("avg_value_5d")) or 0.0
        val20 = parse_numeric(row.get("avg_value_20d")) or 0.0
        val = max(float(val5), float(val20))
        lines.append(f"{i}. {name}({code}) | {val/1e8:.1f}억")
    return lines
