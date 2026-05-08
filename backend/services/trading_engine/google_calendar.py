from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import TradeEngineConfig

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def record_finalize_briefing_to_google_calendar(
    *,
    config: TradeEngineConfig,
    trade_date: str,
    summary_text: str,
    realized_pnl: float,
    realized_pct: float,
    account_summary: str | None = None,
    eval_pct: float | None = None,
    trade_activity_summary: str | None = None,
    logger: logging.Logger = logger,
) -> str | None:
    """Best-effort Google Calendar 기록. 실패해도 매매 마감 흐름은 막지 않는다."""
    if not config.google_calendar_enabled:
        return None
    if not summary_text.strip():
        return None

    try:
        service = _build_calendar_service(
            credentials_path=config.google_calendar_credentials_path,
            token_path=config.google_calendar_token_path,
        )
        if service is None:
            logger.info("trading Google Calendar skipped: credentials/token not ready")
            return None
        event = _build_finalize_event(
            config=config,
            trade_date=trade_date,
            summary_text=summary_text,
            realized_pnl=realized_pnl,
            realized_pct=realized_pct,
            account_summary=account_summary,
            eval_pct=eval_pct,
            trade_activity_summary=trade_activity_summary,
        )
        event_id = _upsert_event_by_private_property(
            service=service,
            calendar_id=config.google_calendar_id,
            property_name="trading_finalize_date",
            property_value=trade_date,
            event=event,
        )
        logger.info("trading Google Calendar finalized event recorded id=%s date=%s", event_id, trade_date)
        return event_id
    except Exception:
        logger.warning("trading Google Calendar finalize record failed date=%s", trade_date, exc_info=True)
        return None


def record_profit_to_google_calendar(
    *,
    config: TradeEngineConfig,
    trade_date: str,
    realized_pnl: float,
    pnl_rate: float | None = None,
    logger: logging.Logger = logger,
) -> str | None:
    """Calendar에는 날짜별 실현손익만 간단히 남긴다."""
    if not config.google_calendar_enabled:
        return None

    try:
        service = _build_calendar_service(
            credentials_path=config.google_calendar_credentials_path,
            token_path=config.google_calendar_token_path,
        )
        if service is None:
            logger.info("trading Google Calendar skipped: credentials/token not ready")
            return None
        event = _build_profit_event(
            config=config,
            trade_date=trade_date,
            realized_pnl=realized_pnl,
            pnl_rate=pnl_rate,
        )
        event_id = _upsert_event_by_private_property(
            service=service,
            calendar_id=config.google_calendar_id,
            property_name="trading_profit_date",
            property_value=trade_date,
            event=event,
        )
        logger.info("trading Google Calendar profit event recorded id=%s date=%s", event_id, trade_date)
        return event_id
    except Exception:
        logger.warning("trading Google Calendar profit record failed date=%s", trade_date, exc_info=True)
        return None


def _build_calendar_service(*, credentials_path: str, token_path: str):
    if not os.path.exists(credentials_path):
        return None
    creds = _load_credentials(token_path=token_path)
    if creds is None:
        return None
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request

            creds.refresh(Request())
            _write_credentials(token_path=token_path, creds=creds)
        else:
            return None
    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _load_credentials(*, token_path: str):
    if not os.path.exists(token_path):
        return None
    from google.oauth2.credentials import Credentials

    return Credentials.from_authorized_user_file(token_path, _SCOPES)


def _write_credentials(*, token_path: str, creds) -> None:
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


def _build_finalize_event(
    *,
    config: TradeEngineConfig,
    trade_date: str,
    summary_text: str,
    realized_pnl: float,
    realized_pct: float,
    account_summary: str | None = None,
    eval_pct: float | None = None,
    trade_activity_summary: str | None = None,
) -> dict[str, object]:
    del summary_text
    tz = ZoneInfo(config.google_calendar_timezone)
    event_start = datetime.strptime(trade_date, "%Y%m%d").replace(
        hour=config.google_calendar_finalize_hour,
        minute=config.google_calendar_finalize_minute,
        tzinfo=tz,
    )
    event_end = event_start + timedelta(minutes=10)
    description_lines = _build_finalize_calendar_lines(
        trade_date=trade_date,
        realized_pnl=realized_pnl,
        eval_pct=eval_pct,
        account_summary=account_summary,
        trade_activity_summary=trade_activity_summary,
    )
    return {
        "summary": f"[매매마감] {trade_date} {realized_pnl:,.0f}원 ({realized_pct:+.2f}%)",
        "description": "\n".join(description_lines),
        "start": {
            "dateTime": event_start.isoformat(),
            "timeZone": config.google_calendar_timezone,
        },
        "end": {
            "dateTime": event_end.isoformat(),
            "timeZone": config.google_calendar_timezone,
        },
        "extendedProperties": {
            "private": {
                "source": "trading_engine_finalize",
                "trading_finalize_date": trade_date,
            },
        },
    }


def _build_finalize_calendar_lines(
    *,
    trade_date: str,
    realized_pnl: float,
    eval_pct: float | None,
    account_summary: str | None,
    trade_activity_summary: str | None,
) -> list[str]:
    lines = [f"[마감] {trade_date}"]
    eval_text = f"{eval_pct:+.2f}%" if eval_pct is not None else "확인불가"
    lines.append(f"손익: 실현 {_format_signed_money(realized_pnl)} / 평가 {eval_text}")
    if account_summary:
        lines.append(f"계좌: {account_summary}")
    trade_lines = _split_trade_activity_lines(trade_activity_summary)
    if trade_lines.get("buy"):
        lines.append(f"매수: {trade_lines['buy']}")
    if trade_lines.get("sell"):
        lines.append(f"청산: {trade_lines['sell']}")
    return lines


def _split_trade_activity_lines(trade_activity_summary: str | None) -> dict[str, str]:
    text = str(trade_activity_summary or "").strip()
    if not text:
        return {}
    result: dict[str, str] = {}
    buy_marker = "매수:"
    sell_marker = "청산:"
    buy_idx = text.find(buy_marker)
    sell_idx = text.find(sell_marker)
    if buy_idx >= 0:
        end = sell_idx if sell_idx > buy_idx else len(text)
        buy_text = text[buy_idx + len(buy_marker) : end].strip(" /")
        if buy_text:
            result["buy"] = buy_text
    if sell_idx >= 0:
        sell_text = text[sell_idx + len(sell_marker) :].strip(" /")
        if sell_text:
            result["sell"] = sell_text
    return result


def _build_profit_event(
    *,
    config: TradeEngineConfig,
    trade_date: str,
    realized_pnl: float,
    pnl_rate: float | None = None,
) -> dict[str, object]:
    start_date = datetime.strptime(trade_date, "%Y%m%d").date()
    end_date = start_date + timedelta(days=1)
    rate_text = f" ({pnl_rate:+.2f}%)" if pnl_rate is not None else ""
    return {
        "summary": f"[자동매매] {realized_pnl:,.0f}원{rate_text}",
        "description": _format_profit_line(realized_pnl=realized_pnl, pnl_rate=pnl_rate),
        "start": {"date": start_date.isoformat()},
        "end": {"date": end_date.isoformat()},
        "extendedProperties": {
            "private": {
                "source": "trading_engine_profit",
                "trading_profit_date": trade_date,
            },
        },
    }


def _format_profit_line(*, realized_pnl: float, pnl_rate: float | None = None) -> str:
    if pnl_rate is None:
        return f"실현손익: {realized_pnl:,.0f}원"
    return f"실현손익: {realized_pnl:,.0f}원 ({pnl_rate:+.2f}%)"


def _format_signed_money(value: float) -> str:
    if value > 0:
        return f"+{value:,.0f}원"
    return f"{value:,.0f}원"


def _upsert_event_by_private_property(
    *,
    service,
    calendar_id: str,
    property_name: str,
    property_value: str,
    event: dict[str, object],
) -> str | None:
    existing = (
        service.events()
        .list(
            calendarId=calendar_id,
            privateExtendedProperty=f"{property_name}={property_value}",
            maxResults=1,
            singleEvents=True,
        )
        .execute()
        .get("items", [])
    )
    if existing:
        event_id = existing[0]["id"]
        updated = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
        return str(updated.get("id") or event_id)
    created = service.events().insert(calendarId=calendar_id, body=event).execute()
    return str(created.get("id") or "")


def authorize_google_calendar_token(
    *,
    credentials_path: str,
    token_path: str,
) -> None:
    """수동 1회 OAuth용. 로컬 터미널에서 실행해 token.json을 생성한다."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, _SCOPES)
    creds = flow.run_local_server(port=0)
    _write_credentials(token_path=token_path, creds=creds)
