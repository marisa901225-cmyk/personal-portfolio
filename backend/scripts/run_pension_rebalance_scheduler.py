from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from pytz import timezone

from backend.core.env_paths import get_project_env_files
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
    if now.month not in {1, 4, 7, 10}:
        return False
    max_day = _env_int("PENSION_REBALANCE_QUARTER_WINDOW_DAYS", 7)
    return 1 <= now.day <= max_day


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_command(*, execute: bool) -> list[str]:
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
    if execute:
        command.append("--execute")
    return command


def _run_rebalance(*, reason: str, force: bool = False) -> int:
    now = datetime.now(KST)
    state_path = _state_path()
    state = _read_state(state_path)
    quarter_key = _quarter_key(now)
    last_success = str(state.get("last_success_quarter") or "")
    execute = _env_bool("PENSION_REBALANCE_EXECUTE", False)

    if not force and last_success == quarter_key:
        logger.info("skip pension rebalance: already completed quarter=%s", quarter_key)
        return 0

    if reason == "schedule" and not _is_quarter_window(now):
        logger.info("skip pension rebalance: outside quarter window now=%s", now.isoformat())
        return 0

    command = _build_command(execute=execute)
    logger.info(
        "starting pension rebalance reason=%s quarter=%s mode=%s command=%s",
        reason,
        quarter_key,
        "EXECUTE" if execute else "DRY_RUN",
        " ".join(command),
    )
    result = subprocess.run(command, cwd=str(PROJECT_ROOT.parent), text=True, capture_output=True)
    if result.stdout:
        logger.info("pension rebalance stdout:\n%s", result.stdout.strip())
    if result.stderr:
        logger.warning("pension rebalance stderr:\n%s", result.stderr.strip())

    if result.returncode == 0:
        state.update(
            {
                "last_success_quarter": quarter_key,
                "last_success_at": now.isoformat(),
                "last_mode": "EXECUTE" if execute else "DRY_RUN",
                "last_reason": reason,
            }
        )
        _write_state(state_path, state)
    else:
        logger.error("pension rebalance failed returncode=%s", result.returncode)
    return int(result.returncode)


async def _run_rebalance_async(reason: str, *, force: bool = False) -> None:
    loop = asyncio.get_running_loop()
    returncode = await loop.run_in_executor(None, lambda: _run_rebalance(reason=reason, force=force))
    if returncode != 0:
        logger.error("pension rebalance job ended with failure returncode=%s", returncode)


async def main() -> None:
    scheduler = AsyncIOScheduler(timezone=KST)
    hour = _env_int("PENSION_REBALANCE_HOUR", 10)
    minute = _env_int("PENSION_REBALANCE_MINUTE", 5)
    scheduler.add_job(
        _run_rebalance_async,
        CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=KST),
        args=["schedule"],
        id="pension_rebalance_quarterly_guarded",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "pension rebalance scheduler started hour=%s minute=%s execute=%s run_on_start=%s",
        hour,
        minute,
        _env_bool("PENSION_REBALANCE_EXECUTE", False),
        _env_bool("PENSION_REBALANCE_RUN_ON_START", True),
    )

    if _env_bool("PENSION_REBALANCE_RUN_ON_START", True):
        await _run_rebalance_async("startup", force=_env_bool("PENSION_REBALANCE_FORCE_START", False))

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
