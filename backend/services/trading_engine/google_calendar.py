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
        )
        event_id = _upsert_event(
            service=service,
            calendar_id=config.google_calendar_id,
            trade_date=trade_date,
            event=event,
        )
        logger.info("trading Google Calendar finalized event recorded id=%s date=%s", event_id, trade_date)
        return event_id
    except Exception:
        logger.warning("trading Google Calendar finalize record failed date=%s", trade_date, exc_info=True)
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
) -> dict[str, object]:
    tz = ZoneInfo(config.google_calendar_timezone)
    event_start = datetime.strptime(trade_date, "%Y%m%d").replace(
        hour=config.google_calendar_finalize_hour,
        minute=config.google_calendar_finalize_minute,
        tzinfo=tz,
    )
    event_end = event_start + timedelta(minutes=10)
    return {
        "summary": f"[매매마감] {trade_date} {realized_pnl:,.0f}원 ({realized_pct:+.2f}%)",
        "description": summary_text,
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


def _upsert_event(*, service, calendar_id: str, trade_date: str, event: dict[str, object]) -> str | None:
    existing = (
        service.events()
        .list(
            calendarId=calendar_id,
            privateExtendedProperty=f"trading_finalize_date={trade_date}",
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
