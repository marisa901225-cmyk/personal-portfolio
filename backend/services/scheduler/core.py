import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from backend.core.db import SessionLocal
from backend.core.time_utils import utcnow, now_kst
from backend.services.news_collector import NewsCollector
from backend.services.scheduler_monitor import monitor_job_async
from backend.services.retry import sync_retry, async_retry


logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
scheduler = AsyncIOScheduler(timezone=KST)

async def job_collect_news():
    """
    주기적 뉴스 수집 작업
    """
    with SessionLocal() as db:
        async with monitor_job_async("collect_game_news", db):
            logger.info("Starting scheduled news collection job...")
            try:
                # 1. RSS 수집
                feeds = [
                    ("Inven LoL", "https://feeds.feedburner.com/inven/lol"),
                ]
                for source_name, url in feeds:
                    sync_retry(NewsCollector.collect_rss)(db, url, source_name)

                # 2. SteamSpy 일반 순위 수집
                await async_retry(NewsCollector.collect_steamspy_rankings)(db)

                # 4. 네이버 뉴스 수집 (E스포츠 + 경제)
                await async_retry(NewsCollector.collect_all_naver_news)(db)

                # 5. 구글 뉴스 수집 (해외 거시경제)
                await async_retry(NewsCollector.collect_all_google_news)(db)

            except Exception as e:
                logger.error(f"News collection job failed: {e}", exc_info=True)
                raise e
            finally:
                logger.info("News collection job finished.")

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
    """
    from backend.services.news.weather import fetch_weather_from_cache
    from backend.services.alarm.processor import process_pending_alarms
    from backend.core.db import SessionLocal
    from backend.services.retry import async_retry
    from backend.integrations.telegram import send_telegram_message
    
    logger.info("Starting Morning Briefing (Weather -> Weekly Derivatives -> Alarm Summary)...")
    
    # 1. 날씨 알림 전송 (캐시 우선)
    try:
        message = await fetch_weather_from_cache()
        if message:
            await send_telegram_message(message)
            logger.info("Morning Briefing: Weather notification sent successfully.")
        else:
            logger.warning("Morning Briefing: Weather message was empty.")
    except Exception as e:
        logger.error(f"Morning Briefing: Weather notification failed: {e}", exc_info=True)

    # 2. 월요일 주간 국내 파생 심리 브리핑
    try:
        now = datetime.now(KST)
        if now.weekday() == 0:  # Monday
            from backend.services.economy.kr_derivatives_weekly_briefing import (
                build_weekly_derivatives_briefing,
            )

            weekly_message = await build_weekly_derivatives_briefing(now=now)
            if weekly_message:
                await send_telegram_message(weekly_message)
                logger.info("Morning Briefing: Weekly derivatives briefing sent.")
            else:
                logger.info("Morning Briefing: Weekly derivatives briefing skipped (not enough data).")
    except Exception as e:
        logger.error(f"Morning Briefing: Weekly derivatives briefing failed: {e}", exc_info=True)

    # 3. 알림 요약 처리 (기존 7시 작업 통합)
    with SessionLocal() as db:
        try:
            await async_retry(process_pending_alarms)(db)
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



def start_scheduler():
    if not scheduler.running:
        # 30분마다 실행 (LLM 알람 처리와 겹침 방지)
        # LLM 농담은 :00, :10, :20... / 뉴스수집은 :07, :37...
        scheduler.add_job(
            job_collect_news, 
            CronTrigger(minute='7,37'), 
            id="collect_game_news", 
            replace_existing=True,
            max_instances=1
        )
        
        # 매일 05:12 - 날씨 프리페치 (재시도 로직 내장)
        scheduler.add_job(
            job_prefetch_weather_05,
            CronTrigger(hour=5, minute=12),
            id="prefetch_weather_05",
            replace_existing=True,
            max_instances=1
        )

        # 매일 06:20 - 경제 스냅샷 프리페치 (VIX 등) / 07:00 브리핑에서 캐시 우선 사용
        scheduler.add_job(
            job_prefetch_economy_0620,
            CronTrigger(hour=6, minute=20),
            id="prefetch_economy_0620",
            replace_existing=True,
            max_instances=1
        )
        
        # 매일 오후 12:30 - 지수 과매도 체크
        # KIS 무료시세: 장 종료 후 오후 12시경(KST) 데이터가 정정되어 유료 시세와 동일해짐
        # 가장 정확한 확정 일봉 데이터를 수집하기 위해 정오 이후인 12:30 실행
        scheduler.add_job(
            job_check_index_oversold,
            CronTrigger(hour=12, minute=30),
            id="check_index_oversold",
            replace_existing=True,
            max_instances=1
        )
        
        # 매일 아침 7시 모닝 브리핑 (캐시 기반 날씨 -> 알림 요약 순차 실행)
        scheduler.add_job(
            job_morning_briefing,
            CronTrigger(hour=7, minute=0),
            id="morning_briefing",
            replace_existing=True,
            max_instances=1
        )

        # 매일 오전 09:05 - 기준금리 변경 체크
        scheduler.add_job(
            job_check_rate_changes,
            CronTrigger(hour=9, minute=5),
            id="check_rate_changes",
            replace_existing=True,
            max_instances=1
        )

        # 평일 15:50 - 국내 옵션 전광판 스냅샷 수집
        scheduler.add_job(
            job_collect_kr_option_snapshot,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=50),
            id="collect_kr_option_snapshot",
            replace_existing=True,
            max_instances=1,
        )


        
        scheduler.start()
        logger.info("AsyncIOScheduler started.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("AsyncIOScheduler shutdown.")
