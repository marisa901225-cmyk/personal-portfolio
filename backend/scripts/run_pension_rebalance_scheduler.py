from __future__ import annotations

import asyncio
import calendar
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from pytz import timezone

from backend.core.env_paths import get_project_env_files
from backend.integrations.kis.trading_adapter import KISDirectCredentials, create_trading_api
from backend.services.pension_order_safety import resolve_pension_product
from backend.core.logging_config import setup_global_logging


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KST = timezone("Asia/Seoul")
DEFAULT_STATE_PATH = PROJECT_ROOT / "storage" / "pension_rebalance" / "state.json"


for env_path in get_project_env_files():
    load_dotenv(env_path)


setup_global_logging(
    level=logging.INFO,
    log_file=str(PROJECT_ROOT / "logs" / "pension_rebalance_scheduler.log"),
)
logger = logging.getLogger("pension_rebalance_scheduler")
_TRADING_JOB_LOCK = asyncio.Lock()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "t", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _state_path() -> Path:
    configured = str(os.getenv("PENSION_REBALANCE_STATE_PATH", "") or "").strip()
    return Path(configured) if configured else DEFAULT_STATE_PATH


def _quarter_key(now: datetime) -> str:
    quarter = ((now.month - 1) // 3) + 1
    return f"{now.year}Q{quarter}"


def _is_quarter_window(now: datetime) -> bool:
    if now.month not in {3, 6, 9, 12}:
        return False
    window_days = max(1, _env_int("PENSION_REBALANCE_QUARTER_WINDOW_DAYS", 7))
    last_day = calendar.monthrange(now.year, now.month)[1]
    first_window_day = max(1, last_day - window_days + 1)
    return first_window_day <= now.day <= last_day


def _should_use_drift_guard(now: datetime, state: dict[str, Any]) -> bool:
    last_success = str(state.get("last_success_quarter") or "")
    return not (_is_quarter_window(now) and last_success != _quarter_key(now))


def _holiday_row_date(row: dict[str, Any]) -> str:
    for key in ("bass_dt", "bss_dt", "stck_bsop_date", "bsop_date", "date"):
        normalized = "".join(ch for ch in str(row.get(key) or "") if ch.isdigit())[:8]
        if len(normalized) == 8:
            return normalized
    return ""


def _open_day_from_holiday_rows(date_key: str, rows: list[dict[str, Any]]) -> bool | None:
    for row in rows:
        if _holiday_row_date(row) != date_key:
            continue
        return str(row.get("opnd_yn") or "").strip().upper() == "Y"
    return None


def _build_pension_kis_api():
    app_key = str(os.getenv("KIS_MY_APP2") or "").strip()
    app_secret = str(os.getenv("KIS_MY_SEC2") or "").strip()
    account = str(os.getenv("KIS_MY_ACCT_STOCK2") or "").strip()
    configured_product = str(os.getenv("KIS_MY_PROD2") or "").strip()
    base_url = str(os.getenv("KIS_PROD") or "https://openapi.koreainvestment.com:9443").strip()
    missing = [
        name
        for name, value in (
            ("KIS_MY_APP2", app_key),
            ("KIS_MY_SEC2", app_secret),
            ("KIS_MY_ACCT_STOCK2", account),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"missing pension KIS env for trading-day lookup: {','.join(missing)}")
    product = resolve_pension_product(account=account, product=configured_product)
    return create_trading_api(
        KISDirectCredentials(
            app_key=app_key,
            app_secret=app_secret,
            account=account,
            product=product,
            base_url=base_url,
            token_slot=2,
        )
    )


def _query_kis_trading_day(date_key: str) -> bool:
    api = _build_pension_kis_api()
    rows = api.domestic_holiday_rows(date_key)
    open_day = _open_day_from_holiday_rows(date_key, rows)
    if open_day is not None:
        return open_day

    previous_day = (datetime.strptime(date_key, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
    next_open = api.next_open_trading_day(previous_day, max_lookahead_days=3)
    return str(next_open or "").strip() == date_key


def _fallback_trading_day(date_key: str) -> bool:
    try:
        parsed = datetime.strptime(date_key, "%Y%m%d").date()
    except ValueError:
        return False
    if parsed.weekday() >= 5:
        return False
    try:
        import holidays

        return parsed not in holidays.country_holidays("KR", years=[parsed.year])
    except Exception:
        return True


def _is_scheduled_trading_day(now: datetime) -> bool:
    date_key = now.strftime("%Y%m%d")
    if now.weekday() >= 5:
        return False
    try:
        return _query_kis_trading_day(date_key)
    except Exception:
        logger.warning("KIS trading-day lookup failed date=%s; using fallback calendar", date_key, exc_info=True)
        return _fallback_trading_day(date_key)


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_command(*, execute: bool, if_drift: bool = False) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "backend.scripts.rebalance_kis_pension_account",
        "--regime",
        str(os.getenv("PENSION_REBALANCE_REGIME_ARG", "auto") or "auto"),
    ]
    min_order_amount = str(os.getenv("PENSION_REBALANCE_MIN_ORDER_AMOUNT", "") or "").strip()
    if min_order_amount:
        command.extend(["--min-order-amount", min_order_amount])
    if _env_bool("PENSION_REBALANCE_NO_SELLS", False):
        command.append("--no-sells")
    if if_drift:
        command.append("--if-drift")
    if execute:
        command.append("--execute")
    return command


def _build_cash_sweep_command(*, execute: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "backend.scripts.rebalance_kis_pension_account",
        "--cash-sweep",
    ]
    min_order_amount = str(os.getenv("PENSION_CASH_SWEEP_MIN_ORDER_AMOUNT", "") or "").strip()
    if not min_order_amount:
        min_order_amount = str(os.getenv("PENSION_REBALANCE_MIN_ORDER_AMOUNT", "") or "").strip()
    if min_order_amount:
        command.extend(["--min-order-amount", min_order_amount])
    if execute:
        command.append("--execute")
    return command


def _run_cash_sweep(*, reason: str) -> int:
    execute = _env_bool("PENSION_CASH_SWEEP_EXECUTE", _env_bool("PENSION_REBALANCE_EXECUTE", False))
    command = _build_cash_sweep_command(execute=execute)
    logger.info(
        "starting pension cash sweep reason=%s mode=%s command=%s",
        reason,
        "EXECUTE" if execute else "DRY_RUN",
        " ".join(command),
    )
    result = subprocess.run(command, cwd=str(PROJECT_ROOT.parent), text=True, capture_output=True)
    if result.stdout:
        logger.info("pension cash sweep stdout:\n%s", result.stdout.strip())
    if result.stderr:
        logger.warning("pension cash sweep stderr:\n%s", result.stderr.strip())
    if result.returncode != 0:
        logger.error("pension cash sweep failed returncode=%s", result.returncode)
    return int(result.returncode)


def _run_rebalance(*, reason: str, force: bool = False) -> int:
    now = datetime.now(KST)
    state_path = _state_path()
    state = _read_state(state_path)
    quarter_key = _quarter_key(now)
    last_success = str(state.get("last_success_quarter") or "")
    execute = _env_bool("PENSION_REBALANCE_EXECUTE", False)
    drift_guarded = False

    if reason == "schedule" and not _is_scheduled_trading_day(now):
        logger.info("skip pension rebalance: non-trading day now=%s", now.isoformat())
        return 0

    if reason == "schedule":
        drift_guarded = _should_use_drift_guard(now, state)
    elif not force and last_success == quarter_key:
        logger.info("skip pension rebalance: already completed quarter=%s", quarter_key)
        return 0

    command = _build_command(execute=execute, if_drift=drift_guarded)
    logger.info(
        "starting pension rebalance reason=%s quarter=%s guard=%s mode=%s command=%s",
        reason,
        quarter_key,
        "DRIFT" if drift_guarded else "QUARTERLY",
        "EXECUTE" if execute else "DRY_RUN",
        " ".join(command),
    )
    result = subprocess.run(command, cwd=str(PROJECT_ROOT.parent), text=True, capture_output=True)
    if result.stdout:
        logger.info("pension rebalance stdout:\n%s", result.stdout.strip())
    if result.stderr:
        logger.warning("pension rebalance stderr:\n%s", result.stderr.strip())

    if result.returncode == 0:
        state.update({"last_check_at": now.isoformat(), "last_mode": "EXECUTE" if execute else "DRY_RUN"})
        if drift_guarded:
            state.update({"last_drift_check_at": now.isoformat(), "last_reason": "drift_schedule"})
        else:
            state.update(
                {
                    "last_success_quarter": quarter_key,
                    "last_success_at": now.isoformat(),
                    "last_reason": reason,
                }
            )
        _write_state(state_path, state)
    else:
        logger.error("pension rebalance failed returncode=%s", result.returncode)
    return int(result.returncode)


async def _run_rebalance_async(reason: str, *, force: bool = False) -> None:
    async with _TRADING_JOB_LOCK:
        loop = asyncio.get_running_loop()
        returncode = await loop.run_in_executor(None, lambda: _run_rebalance(reason=reason, force=force))
    if returncode != 0:
        logger.error("pension rebalance job ended with failure returncode=%s", returncode)


async def _run_cash_sweep_async(reason: str) -> None:
    async with _TRADING_JOB_LOCK:
        loop = asyncio.get_running_loop()
        returncode = await loop.run_in_executor(None, lambda: _run_cash_sweep(reason=reason))
    if returncode != 0:
        logger.error("pension cash sweep job ended with failure returncode=%s", returncode)


async def main() -> None:
    scheduler = AsyncIOScheduler(timezone=KST)
    hour = _env_int("PENSION_REBALANCE_HOUR", 10)
    minute = _env_int("PENSION_REBALANCE_MINUTE", 5)
    cash_sweep_hour = _env_int("PENSION_CASH_SWEEP_HOUR", 10)
    cash_sweep_minute = _env_int("PENSION_CASH_SWEEP_MINUTE", 15)
    scheduler.add_job(
        _run_rebalance_async,
        CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=KST),
        args=["schedule"],
        id="pension_rebalance_daily_guarded",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_cash_sweep_async,
        CronTrigger(day_of_week="mon-fri", hour=cash_sweep_hour, minute=cash_sweep_minute, timezone=KST),
        args=["schedule"],
        id="pension_cash_sweep_daily",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "pension rebalance scheduler started hour=%s minute=%s execute=%s run_on_start=%s cash_sweep_hour=%s cash_sweep_minute=%s cash_sweep_execute=%s",
        hour,
        minute,
        _env_bool("PENSION_REBALANCE_EXECUTE", False),
        _env_bool("PENSION_REBALANCE_RUN_ON_START", False),
        cash_sweep_hour,
        cash_sweep_minute,
        _env_bool("PENSION_CASH_SWEEP_EXECUTE", _env_bool("PENSION_REBALANCE_EXECUTE", False)),
    )

    if _env_bool("PENSION_REBALANCE_RUN_ON_START", False):
        await _run_rebalance_async("startup", force=_env_bool("PENSION_REBALANCE_FORCE_START", False))
    if _env_bool("PENSION_CASH_SWEEP_RUN_ON_START", False):
        await _run_cash_sweep_async("startup")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
