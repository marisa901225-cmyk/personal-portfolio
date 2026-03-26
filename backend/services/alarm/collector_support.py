import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Type

from fastapi import HTTPException, Request
from pydantic import BaseModel


def env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except Exception:
        return default


def parse_hhmm_to_minutes(value: str) -> int:
    value = (value or "").strip()
    if not value:
        raise ValueError("empty time")
    if value == "24:00":
        return 24 * 60
    hour, minute = map(int, value.split(":", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid time: {value}")
    return hour * 60 + minute


def _minute_anchor(now: datetime, minute_of_day: int, *, day_offset: int = 0) -> datetime:
    return (now + timedelta(days=day_offset)).replace(
        hour=minute_of_day // 60,
        minute=minute_of_day % 60,
        second=0,
        microsecond=0,
    )


def alarm_silence_active_window_minutes(raw_value: Optional[str]) -> tuple[int, int]:
    raw = (raw_value or "07:00-23:00").strip().lower()
    if raw in {"", "off", "disabled", "none", "0"}:
        return (0, 24 * 60)
    if "-" not in raw:
        return (0, 24 * 60)

    start_raw, end_raw = [p.strip() for p in raw.split("-", 1)]
    try:
        start_min = parse_hhmm_to_minutes(start_raw)
        end_min = parse_hhmm_to_minutes(end_raw)
    except Exception:
        return (0, 24 * 60)

    if not (0 <= start_min < 24 * 60) or not (0 <= end_min <= 24 * 60):
        return (0, 24 * 60)
    if start_min == 0 and end_min == 24 * 60:
        return (0, 24 * 60)
    if start_min == end_min:
        return (0, 24 * 60)
    return (start_min, end_min)


def alarm_silence_window_for_now(
    now: datetime,
    *,
    raw_value: Optional[str],
) -> tuple[bool, Optional[datetime]]:
    start_min, end_min = alarm_silence_active_window_minutes(raw_value)
    if (start_min, end_min) == (0, 24 * 60):
        return True, None

    now_min = now.hour * 60 + now.minute
    if start_min < end_min:
        if start_min <= now_min < end_min:
            return True, _minute_anchor(now, start_min)
        return False, None

    if not (now_min >= start_min or now_min < end_min):
        return False, None
    if now_min >= start_min:
        return True, _minute_anchor(now, start_min)
    return True, _minute_anchor(now, start_min, day_offset=-1)


def parse_timestamp(value: Optional[str], *, fallback_now: bool = True) -> Optional[datetime]:
    if not value:
        return datetime.now() if fallback_now else None
    try:
        raw = value.strip()
        if raw.replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(raw))
        return datetime.fromisoformat(raw.replace("Z", "+00:00").replace("T", " ")).replace(tzinfo=None)
    except Exception:
        return datetime.now() if fallback_now else None


def parse_last_seen(value: Optional[str]) -> Optional[datetime]:
    return parse_timestamp(value, fallback_now=False)


def require_bearer_token(api_token: Optional[str], authorization: Optional[str], logger: logging.Logger) -> None:
    if not api_token:
        logger.error("API_TOKEN not configured")
        raise HTTPException(status_code=500, detail="Server configuration error")

    scheme, _, token = (authorization or "").partition(" ")
    if scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    if token != api_token:
        raise HTTPException(status_code=403, detail="Invalid token")


async def parse_request_model(
    request: Request,
    model_cls: Type[BaseModel],
    logger: logging.Logger,
    *,
    flexible: bool = False,
) -> BaseModel:
    try:
        data = await request.json()
    except Exception as e:
        if not flexible:
            logger.error("%s JSON Parsing Error: %s", model_cls.__name__, e)
            raise HTTPException(status_code=422, detail=f"Invalid JSON format: {e}")
        try:
            body_str = (await request.body()).decode("utf-8")
            if body_str.startswith('"') and body_str.endswith('"'):
                body_str = json.loads(body_str, strict=False)
            data = json.loads(body_str, strict=False)
        except Exception as ex:
            logger.error("%s JSON Parsing Error: %s", model_cls.__name__, ex)
            raise HTTPException(status_code=422, detail=f"Invalid JSON format: {ex}")

    if flexible and isinstance(data, str):
        try:
            data = json.loads(data, strict=False)
        except Exception as e:
            logger.error("%s JSON Parsing Error: %s", model_cls.__name__, e)
            raise HTTPException(status_code=422, detail=f"Invalid JSON format: {e}")

    try:
        return model_cls(**data)
    except Exception as e:
        logger.error("%s JSON Parsing Error: %s", model_cls.__name__, e)
        raise HTTPException(status_code=422, detail=f"Invalid JSON format: {e}")
