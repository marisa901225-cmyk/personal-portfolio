"""
E-Sports Match Notification Service

경기 시작/종료/임박 알림을 담당하는 모듈.
esports_monitor.py에서 분리하여 코드 가독성 향상.
"""
import random
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ...core.models import EsportsMatch
from ...core.time_utils import utcnow, now_kst, format_kst_time
from ...core.esports_config import GAME_REGISTRY, infer_league_tag_from_name, is_league_in_active_window
from ...integrations.telegram import send_telegram_message
from ..alarm.catchphrase_constants import build_fallback_lines

logger = logging.getLogger(__name__)


def _check_league_active(league_tag: str, game_slug: str, current_kst: datetime) -> bool:
    """Check if a specific league is within its active time window"""
    weekday = current_kst.weekday()
    current_time = current_kst.hour * 60 + current_kst.minute
    return is_league_in_active_window(league_tag, game_slug, weekday, current_time)


async def notify_match_finished(
    match: EsportsMatch,
    api_data: dict,
    dry_run: bool = False
) -> bool:
    """경기 종료 알림 전송
    
    Returns:
        True if notification was sent (or skipped due to time window), False if error
    """
    # Check idempotency
    if match.finished_notified_at:
        logger.debug(f"Match {match.match_id} already notified, skipping")
        return True

    # Get league tag for time window check
    config = GAME_REGISTRY.get(match.videogame, {})
    tagger = config.get("tagger")
    league_tag = tagger(api_data) if tagger else "default"
    
    current_kst = now_kst()
    
    # Check if we're in active window for this league
    if not _check_league_active(league_tag, match.videogame, current_kst):
        logger.info(f"Skipping notification for {match.name} - outside {league_tag} active window")
        match.finished_notified_at = utcnow()  # Mark as handled
        return True

    if dry_run:
        logger.info(f"[DRY RUN] Would notify: Match {match.name} finished")
    else:
        winner = api_data.get("winner", {}).get("name", "TBD")
        msg = (
            f"🏁 <b>경기 종료!</b>\n\n"
            f"🏆 {match.name}\n"
            f"🥇 <b>승리팀: {winner}</b>\n"
            f"⏰ 종료 시각: {current_kst.strftime('%H:%M')} (KST)"
        )
        try:
            await send_telegram_message(msg)
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")
            return False

    match.finished_notified_at = utcnow()
    return True


async def notify_match_start(
    match_id: int,
    videogame: str,
    name: str,
    stream_url: Optional[str] = None
) -> bool:
    """경기 시작 알림 전송"""
    current_kst = now_kst()
    league_tag = infer_league_tag_from_name(name, videogame)
    
    if not _check_league_active(league_tag, videogame, current_kst):
        logger.info(f"Skipping start notification for {name} - outside {league_tag} active window")
        return True
    
    game_key = "LoL" if videogame == "league-of-legends" else "Valorant"
    catchphrases = build_fallback_lines(game_key=game_key)
    phrase = random.choice(catchphrases)

    msg = (
        f"🎬 <b>{phrase}</b>\n\n"
        f"🏆 {name}\n"
        f"⏰ 시작 시각: {current_kst.strftime('%H:%M')} (KST)"
    )
    try:
        await send_telegram_message(msg)
        logger.info(f"Sent start notification for match {match_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send start notification for {match_id}: {e}")
        return False


async def notify_pre_match(
    match_id: int,
    name: str,
    scheduled_at: datetime,
    videogame: str = "league-of-legends"
) -> bool:
    """경기 10분 전 알림 전송"""
    current_kst = now_kst()
    league_tag = infer_league_tag_from_name(name, videogame)
    
    if not _check_league_active(league_tag, videogame, current_kst):
        logger.info(f"Skipping pre-match notification for {name} - outside {league_tag} active window")
        return True
    
    time_str = format_kst_time(scheduled_at)
    msg = (
        f"⏳ <b>경기 시작 10분 전!</b>\n\n"
        f"🏆 {name}\n"
        f"⏰ 예정 시각: {time_str} (KST)"
    )
    try:
        await send_telegram_message(msg)
        logger.info(f"Sent pre-match notification for match {match_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send pre-match notification for {match_id}: {e}")
        return False


async def notify_next_match(db: Session, finished_match: EsportsMatch) -> Optional[EsportsMatch]:
    """다음 경기 찾아서 알림 전송
    
    Returns:
        Next match if found, None otherwise
    """
    # Build query conditions
    conds = [
        EsportsMatch.status == "not_started",
        EsportsMatch.scheduled_at.isnot(None)
    ]
    if finished_match.serie_id:
        conds.append(EsportsMatch.serie_id == finished_match.serie_id)
    elif finished_match.tournament_id:
        conds.append(EsportsMatch.tournament_id == finished_match.tournament_id)
    else:
        return None

    next_match = db.query(EsportsMatch).filter(*conds).order_by(
        EsportsMatch.scheduled_at.asc()
    ).first()

    if next_match and next_match.scheduled_at:
        # [FIX] Check if we're in active window for this league before sending notification
        current_kst = now_kst()
        league_tag = infer_league_tag_from_name(next_match.name, next_match.videogame)
        
        if not _check_league_active(league_tag, next_match.videogame, current_kst):
            logger.info(f"Skipping next match notification for {next_match.name} - outside {league_tag} active window")
            return next_match  # Return the match but skip notification
        
        time_str = format_kst_time(next_match.scheduled_at)
        msg = (
            f"📅 <b>다음 경기 안내</b>\n\n"
            f"🏆 {next_match.name}\n"
            f"⏰ 예정 시각: {time_str} (KST)"
        )
        try:
            await send_telegram_message(msg)
            logger.info(f"Next match found in cache: {next_match.name} at {next_match.scheduled_at}")
        except Exception as e:
            logger.error(f"Failed to send next match notification: {e}")
        return next_match
    else:
        logger.info(f"No cached next match found for {finished_match.videogame}")
        return None
