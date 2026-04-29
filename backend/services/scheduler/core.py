import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.core.db import SessionLocal
from backend.services.auth_secret_rotation import (
    load_auth_secret_rotation_config_from_env,
    rotate_backend_auth_secrets,
)
from backend.services.news_collector import NewsCollector
from backend.services.retry import async_retry, sync_retry
from backend.services.scheduler_monitor import monitor_job_async
from backend.services.trading_engine.archive import archive_trading_engine_weekly
from backend.services.trading_engine.parking import is_regular_market_open
from backend.services.trading_engine.runtime import (
    close_bot as close_trading_bot,
    get_or_create_bot,
    load_config_from_env as load_trading_engine_config,
    trading_engine_enabled,
)

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
scheduler = AsyncIOScheduler(timezone=KST)
_trading_engine_cycle_lock = asyncio.Lock()
_trading_engine_lock_monitor_lock = asyncio.Lock()

_SCHEDULER_ROLES = {"all", "news", "trading"}


def _trading_interval_minutes() -> int:
    raw = os.getenv("TRADING_ENGINE_SCHEDULE_INTERVAL_MIN", "2")
    try:
        value = int(raw)
    except ValueError:
        return 2
    return max(1, min(15, value))


def _periodic_minute_field(*, interval: int, exclude_minutes: set[int] | None = None) -> str:
    excluded = {minute for minute in (exclude_minutes or set()) if 0 <= minute <= 59}
    minutes = [str(minute) for minute in range(0, 60, max(1, interval)) if minute not in excluded]
    return ",".join(minutes)


def _trading_lock_monitor_interval_seconds() -> int:
    raw = os.getenv("TRADING_ENGINE_LOCK_MONITOR_INTERVAL_SEC", "10")
    try:
        value = int(raw)
    except ValueError:
        return 10
    return max(5, min(30, value))


def _scheduler_role() -> str:
    raw = str(os.getenv("SCHEDULER_ROLE", "all") or "").strip().lower()
    if raw in _SCHEDULER_ROLES:
        return raw
    logger.warning("Unknown SCHEDULER_ROLE=%r. Falling back to 'all'.", raw)
    return "all"


def _runs_news_jobs(role: str) -> bool:
    return role in {"all", "news"}


def _runs_trading_jobs(role: str) -> bool:
    return role in {"all", "trading"}


async def job_collect_news():
    """
    주기적 뉴스 수집 작업
    """
    with SessionLocal() as db:
        async with monitor_job_async("collect_game_news", db):
            logger.info("Starting scheduled news collection job...")
            try:
                for source_name, url in NewsCollector.RSS_FEEDS.items():
                    sync_retry(NewsCollector.collect_rss)(db, url, source_name)

                await async_retry(NewsCollector.collect_steamspy_rankings)(db)
                await async_retry(NewsCollector.collect_all_naver_news)(db)
                await async_retry(NewsCollector.collect_all_google_news)(db)

            except Exception as e:
                logger.error(f"News collection job failed: {e}", exc_info=True)
                raise e
            finally:
                logger.info("News collection job finished.")


async def job_collect_premarket_news():
    """
    매일 06:55 장전 브리핑 직전 시장 뉴스만 한 번 더 수집한다.

    - 장전 브리핑 최신성 보강 목적
    - 게임/RSS 수집은 제외하고 경제 뉴스만 실행
    """
    with SessionLocal() as db:
        async with monitor_job_async("collect_premarket_news", db):
            logger.info("Starting premarket news collection job...")
            try:
                await async_retry(NewsCollector.collect_all_naver_news)(db)
                await async_retry(NewsCollector.collect_all_google_news)(db)
            except Exception as e:
                logger.error(f"Premarket news collection job failed: {e}", exc_info=True)
                raise e
            finally:
                logger.info("Premarket news collection job finished.")


async def job_prefetch_weather_05():
    """
    매일 05:12 날씨 프리페치 수집 (재시도 로직 내장)

    05:12, 05:25, 05:45, 06:20에 자동 재시도
    성공 시 캐시 저장 후 종료
    """
    from backend.services.news.weather import prefetch_weather_at_05

    logger.info("Starting 05:12 weather prefetch job...")
    try:
        await prefetch_weather_at_05()
        logger.info("Weather prefetch job completed.")
    except Exception as e:
        logger.error(f"Weather prefetch job failed: {e}", exc_info=True)


async def job_prefetch_economy_0620():
    """
    매일 06:20 경제 스냅샷 프리페치 (특히 VIX) 후 캐시 저장
    07:00 모닝 브리핑에서 우선 사용
    """
    from backend.services.economy.economy_service import EconomyService

    logger.info("Starting 06:20 economy snapshot prefetch job...")
    try:
        await EconomyService.prefetch_morning_snapshot_cache()
        logger.info("Economy snapshot prefetch job completed.")
    except Exception as e:
        logger.error(f"Economy snapshot prefetch job failed: {e}", exc_info=True)


async def job_morning_briefing():
    """
    매일 아침 7시 모닝 브리핑 (날씨 -> 알림 요약 순차 실행)

    날씨는 캐시 우선 (05시 프리페치 데이터 사용)
    월요일 주간 파생심리 브리핑은 날씨 메시지 내부 컨텍스트로 함께 녹인다.
    """
    from backend.integrations.telegram import send_telegram_message
    from backend.services.alarm.processor import process_pending_alarms
    from backend.services.news.weather import fetch_weather_from_cache

    logger.info("Starting Morning Briefing (Weather with weekly derivatives context -> Alarm Summary)...")

    try:
        message = await fetch_weather_from_cache()
        if message:
            await send_telegram_message(message)
            logger.info("Morning Briefing: Weather notification sent successfully.")
        else:
            logger.warning("Morning Briefing: Weather message was empty.")
    except Exception as e:
        logger.error(f"Morning Briefing: Weather notification failed: {e}", exc_info=True)

    with SessionLocal() as db:
        try:
            from backend.core.config import settings

            briefing_kwargs = {
                "model_override": "openai/gpt-5.1-chat",
                "api_key": settings.open_api_key,
                "base_url": "https://openrouter.ai/api/v1",
            }
            await async_retry(process_pending_alarms)(db, **briefing_kwargs)
        except Exception as e:
            logger.error(f"Morning Briefing: Alarm processing failed: {e}", exc_info=True)

    logger.info("Morning Briefing completed.")


async def job_collect_kr_option_snapshot():
    """
    국내 옵션 전광판 스냅샷 수집 (평일 장마감 직전 15:50 KST)

    - API 권장 호출빈도(초당 1건) 이슈를 피하기 위해 단일 호출만 수행
    - 월요일 주간 브리핑에 사용할 일별 스냅샷을 파일 캐시에 누적 저장
    """
    from backend.services.economy.kr_derivatives_weekly_briefing import collect_option_board_snapshot

    with SessionLocal() as db:
        async with monitor_job_async("collect_kr_option_snapshot", db):
            logger.info("Starting KR option board snapshot collection job...")
            try:
                snapshot = await collect_option_board_snapshot()
                if snapshot:
                    logger.info(
                        "KR option snapshot saved: date=%s pcr=%.3f",
                        snapshot.trading_date,
                        snapshot.put_call_bid_ratio,
                    )
                else:
                    logger.warning("KR option snapshot collection returned no data.")
            except Exception as e:
                logger.error(f"KR option snapshot collection job failed: {e}", exc_info=True)
                raise e


async def job_check_index_oversold():
    """
    지수 과매도 체크 작업 (SPY, QQQ)

    미국 장 마감 후 실행 (한국 시간 새벽 5시 또는 6시)
    일봉 데이터를 수집하여 RSI, MA, BB 지표를 계산하고
    과매도 구간 진입 시 알람 전송
    """
    from backend.services.index_alarm_service import check_all_indices

    with SessionLocal() as db:
        async with monitor_job_async("check_index_oversold", db):
            logger.info("Starting index oversold check job...")
            try:
                await check_all_indices()
                logger.info("Index oversold check job completed.")
            except Exception as e:
                logger.error(f"Index oversold check job failed: {e}", exc_info=True)
                raise e


async def job_check_rate_changes():
    """
    한국은행 기준금리 / 미국 기준금리 변경 알림 체크
    """
    from backend.services.economy.rate_alerts import check_rate_changes_and_notify

    logger.info("Starting rate change check job...")
    try:
        changed = await check_rate_changes_and_notify()
        if changed:
            logger.info("Rate change alert sent.")
        else:
            logger.info("No rate changes detected.")
    except Exception as e:
        logger.error(f"Rate change check job failed: {e}", exc_info=True)


async def job_trading_engine_cycle():
    """
    하이브리드 트레이딩 엔진 주기 실행.

    - run_once 내부에서 휴장일/장시간/리스크 게이트를 처리
    - asyncio.to_thread로 이벤트 루프 블로킹 방지
    """
    bot = get_or_create_bot()
    if bot is None:
        return

    if _trading_engine_cycle_lock.locked():
        logger.warning("trading_engine_cycle skipped: previous cycle still running")
        return

    async with _trading_engine_cycle_lock:
        await _run_trading_engine_cycle(bot)


async def _run_trading_engine_cycle(bot):
    with SessionLocal() as db:
        async with monitor_job_async("trading_engine_cycle", db):
            result = await asyncio.to_thread(bot.run_once, datetime.now(KST))
            logger.info("trading_engine_cycle result=%s", result)


async def job_trading_engine_lock_monitor():
    """
    LOCK arm 상태의 단타 포지션만 장중에 더 촘촘히 감시한다.

    - 본 사이클이 돌고 있으면 충돌 방지를 위해 스킵
    - 장중 정규장 시간 외에는 실행하지 않음
    """
    bot = get_or_create_bot()
    if bot is None:
        return

    now = datetime.now(KST)
    if not is_regular_market_open(now):
        return
    if not bot.has_armed_day_profit_locks():
        return
    if _trading_engine_lock_monitor_lock.locked():
        logger.debug("trading_engine_lock_monitor skipped: previous monitor still running")
        return

    async with _trading_engine_lock_monitor_lock:
        result = await asyncio.to_thread(bot.run_locked_profit_monitor, now)
        logger.info("trading_engine_lock_monitor result=%s", result)


async def job_trading_engine_finalize():
    """
    장 종료 후 거래일지 요약 알림 전송.
    """
    bot = get_or_create_bot()
    if bot is None:
        return

    with SessionLocal() as db:
        async with monitor_job_async("trading_engine_finalize", db):
            summary_text = await asyncio.to_thread(bot.finalize_day)
            logger.info("trading_engine_finalize summary=%s", summary_text)


async def job_trading_engine_weekly_archive():
    """
    토요일 주간 아카이브.

    - output 디렉토리 산출물과 runlog를 DB로 흡수
    - state.json은 스냅샷만 보관하고 원본 파일은 유지
    - 성공 후 output 파일 삭제, runlog는 비움
    """
    config = load_trading_engine_config()

    with SessionLocal() as db:
        async with monitor_job_async("trading_engine_weekly_archive", db):
            result = archive_trading_engine_weekly(
                db,
                config=config,
                now=datetime.now(KST),
            )
            logger.info("trading_engine_weekly_archive result=%s", result)


async def job_rotate_backend_auth_secrets():
    """
    인증용 비밀키 회전 스케줄러.

    - 외부 secrets env 파일의 API_TOKEN / JWT_SECRET_KEY를 갱신한다.
    - 첫 실행은 env 파일 mtime을 기준으로 상태만 심고, 즉시 회전은 하지 않는다.
    - 회전 후에는 텔레그램으로 env 반영 확인 및 서비스 재생성 안내를 보낸다.
    """
    config = load_auth_secret_rotation_config_from_env()

    with SessionLocal() as db:
        async with monitor_job_async("rotate_backend_auth_secrets", db):
            result = await asyncio.to_thread(
                rotate_backend_auth_secrets,
                config=config,
            )
            logger.info("rotate_backend_auth_secrets result=%s", result)


def start_scheduler():
    if not scheduler.running:
        role = _scheduler_role()
        logger.info("Scheduler role=%s", role)

        if _runs_news_jobs(role):
            scheduler.add_job(
                job_collect_news,
                CronTrigger(minute="7,37"),
                id="collect_game_news",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_prefetch_weather_05,
                CronTrigger(hour=5, minute=12),
                id="prefetch_weather_05",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_prefetch_economy_0620,
                CronTrigger(hour=6, minute=20),
                id="prefetch_economy_0620",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_collect_premarket_news,
                CronTrigger(hour=6, minute=55),
                id="collect_premarket_news",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_check_index_oversold,
                CronTrigger(hour=12, minute=30),
                id="check_index_oversold",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_morning_briefing,
                CronTrigger(hour=7, minute=0),
                id="morning_briefing",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_check_rate_changes,
                CronTrigger(hour=9, minute=5),
                id="check_rate_changes",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_collect_kr_option_snapshot,
                CronTrigger(day_of_week="mon-fri", hour=15, minute=50),
                id="collect_kr_option_snapshot",
                replace_existing=True,
                max_instances=1,
            )

            auth_rotation_config = load_auth_secret_rotation_config_from_env()
            if auth_rotation_config.enabled:
                scheduler.add_job(
                    job_rotate_backend_auth_secrets,
                    CronTrigger(
                        hour=auth_rotation_config.check_hour,
                        minute=auth_rotation_config.check_minute,
                    ),
                    id="rotate_backend_auth_secrets",
                    replace_existing=True,
                    max_instances=1,
                )
                logger.info(
                    "Backend auth rotation job registered (%02d:%02d KST, interval=%s days)",
                    auth_rotation_config.check_hour,
                    auth_rotation_config.check_minute,
                    auth_rotation_config.interval_days,
                )
            else:
                logger.info("Backend auth rotation job skipped (BACKEND_AUTH_ROTATE_ENABLED != true)")
        else:
            logger.info("News scheduler jobs skipped (SCHEDULER_ROLE=%s)", role)

        if _runs_trading_jobs(role) and trading_engine_enabled():
            interval = _trading_interval_minutes()
            lock_monitor_interval_sec = _trading_lock_monitor_interval_seconds()
            morning_periodic_minutes = _periodic_minute_field(interval=interval, exclude_minutes={5, 55})
            midday_periodic_minutes = _periodic_minute_field(interval=interval)
            afternoon_periodic_minutes = _periodic_minute_field(interval=interval, exclude_minutes={0, 55})

            scheduler.add_job(
                job_trading_engine_cycle,
                CronTrigger(day_of_week="mon-fri", hour=8, minute="50,54,58"),
                id="trading_engine_cycle_preopen",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_trading_engine_cycle,
                CronTrigger(day_of_week="mon-fri", hour=9, minute=morning_periodic_minutes),
                id="trading_engine_cycle_intraday_morning",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_trading_engine_cycle,
                CronTrigger(day_of_week="mon-fri", hour="10-12,14", minute=midday_periodic_minutes),
                id="trading_engine_cycle_intraday_midday",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_trading_engine_cycle,
                CronTrigger(day_of_week="mon-fri", hour=13, minute=afternoon_periodic_minutes),
                id="trading_engine_cycle_intraday_afternoon",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_trading_engine_lock_monitor,
                CronTrigger(day_of_week="mon-fri", hour="9-15", second=f"*/{lock_monitor_interval_sec}"),
                id="trading_engine_lock_monitor",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_trading_engine_cycle,
                CronTrigger(day_of_week="mon-fri", hour=15, minute="0,4,8,12,16,20,24,28"),
                id="trading_engine_cycle_intraday_close",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_trading_engine_finalize,
                CronTrigger(day_of_week="mon-fri", hour=15, minute=31),
                id="trading_engine_finalize",
                replace_existing=True,
                max_instances=1,
            )

            scheduler.add_job(
                job_trading_engine_weekly_archive,
                CronTrigger(day_of_week="sat", hour=6, minute=40),
                id="trading_engine_weekly_archive",
                replace_existing=True,
                max_instances=1,
            )
            logger.info("Trading engine scheduler jobs registered (interval=%s min)", interval)
        else:
            logger.info(
                "Trading engine scheduler jobs skipped (SCHEDULER_ROLE=%s, TRADING_ENGINE_ENABLED=%s)",
                role,
                trading_engine_enabled(),
            )

        scheduler.start()
        logger.info("AsyncIOScheduler started.")


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        close_trading_bot()
        logger.info("AsyncIOScheduler shutdown.")
