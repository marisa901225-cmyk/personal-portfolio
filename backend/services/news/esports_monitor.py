"""
E-Sports Smart Polling Monitor

PandaScore REST API 기반으로 매치 상태 변화(running → finished)를 감지하고,
다음 경기 알람을 갱신하는 스마트 폴링 시스템.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Set, Any

import httpx
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from ...core.config import settings
from ...core.db import SessionLocal
from ...core.models import EsportsMatch
from ...core.time_utils import utcnow, now_kst
from ...core.esports_config import get_game_config, GAME_REGISTRY
from .core import PANDASCORE_URL
from .esports_notifier import (
    notify_match_finished, notify_match_start, 
    notify_pre_match, notify_next_match
)

def is_retryable_status(exception):
    """429 Too Many Requests 또는 5xx Server Error인 경우에만 재시도"""
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code == 429 or 500 <= exception.response.status_code < 600
    return isinstance(exception, httpx.TimeoutException)


logger = logging.getLogger(__name__)

# Active Windows Configuration (KST time)
ACTIVE_WINDOWS = {
    # LCK Challengers: Mon 13:30-21:30, Tue 16:30-21:30
    "lck_cl": [
        {"weekday": 0, "start": (13, 30), "end": (21, 30)},  # Monday
        {"weekday": 1, "start": (16, 30), "end": (21, 30)},  # Tuesday
    ],
    # General Evening (for LCK/LPL/VCT main events)
    "evening": [
        {"weekday": i, "start": (18, 0), "end": (25, 0)} for i in range(7)  # 18:00 KST Start
    ],
}

# Polling intervals (seconds)
POLL_INTERVAL_ACTIVE = 60      # During active windows or match imminent
POLL_INTERVAL_IDLE = 600       # 10 minutes when idle
POLL_INTERVAL_THROTTLED = 180  # When rate limit is low
UPCOMING_INDEX_INTERVAL = 600   # 10 minutes for upcoming indexer (reduced API calls)

# Rate limit thresholds
RATE_LIMIT_WARN_THRESHOLD = 100   # Start being careful
RATE_LIMIT_CRITICAL = 50          # Switch to throttled mode

# Double-check threshold (prevent ghost finish events)
MISSING_THRESHOLD = 2


class EsportsMonitor:
    """PandaScore 기반 스마트 폴링 모니터"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.api_key = settings.pandascore_api_key
        self.running = False
        self._rate_limit_remaining: Optional[int] = None
        self._client: Optional[httpx.AsyncClient] = None

    def _is_in_active_window(self, now_kst: datetime) -> bool:
        """Check if current time is within any active window"""
        weekday = now_kst.weekday()
        current_hour = now_kst.hour
        current_minute = now_kst.minute
        current_time = current_hour * 60 + current_minute

        for window_type, windows in ACTIVE_WINDOWS.items():
            for w in windows:
                start_time = w["start"][0] * 60 + w["start"][1]
                end_time = w["end"][0] * 60 + w["end"][1]
                
                # [FIXED] Overnight window logic: Check both today and yesterday
                if end_time > 24 * 60:
                    next_weekday = (w["weekday"] + 1) % 7
                    # Case 1: Start of window (today is the primary day)
                    if weekday == w["weekday"] and current_time >= start_time:
                        return True
                    # Case 2: End of window (today is the day after the primary day)
                    if weekday == next_weekday and current_time < (end_time - 24 * 60):
                        return True
                elif w["weekday"] == weekday and start_time <= current_time < end_time:
                    return True
        return False

    def _has_imminent_match(self, db: Session) -> bool:
        """Check if there's a match starting within 30 minutes"""
        now = utcnow()
        threshold = now + timedelta(minutes=30)
        imminent = db.query(EsportsMatch).filter(
            EsportsMatch.status == "not_started",
            EsportsMatch.scheduled_at.isnot(None),
            EsportsMatch.scheduled_at >= now,  # [FIXED] Prevent past matches from triggering
            EsportsMatch.scheduled_at <= threshold
        ).first()
        return imminent is not None

    def _get_poll_interval(self, db: Session) -> int:
        """Determine current polling interval based on context"""
        current_kst = now_kst()
        base = POLL_INTERVAL_ACTIVE if (
            self._is_in_active_window(current_kst) or self._has_imminent_match(db)
        ) else POLL_INTERVAL_IDLE

        # rate limit: 절대 더 빨라지지 않게 max()로만 느리게
        if self._rate_limit_remaining is not None:
            if self._rate_limit_remaining < RATE_LIMIT_CRITICAL:
                logger.warning(f"Rate limit critical ({self._rate_limit_remaining}), throttling")
                return max(base, POLL_INTERVAL_THROTTLED)
            if self._rate_limit_remaining < RATE_LIMIT_WARN_THRESHOLD:
                logger.info(f"Rate limit low ({self._rate_limit_remaining}), slightly throttling")
                return max(base, POLL_INTERVAL_ACTIVE * 2)

        return base

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(is_retryable_status),  # [FIXED] Only retry 429 and 5xx
    )
    async def _fetch(self, endpoint: str, params: dict = None) -> Any:
        """Fetch from PandaScore API with rate limit tracking"""
        if not self._client:
            self._client = httpx.AsyncClient(timeout=20.0)

        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{PANDASCORE_URL}{endpoint}"

        response = await self._client.get(url, headers=headers, params=params or {})
        response.raise_for_status()

        # Track rate limit
        remaining = response.headers.get("X-Rate-Limit-Remaining")
        if remaining:
            self._rate_limit_remaining = int(remaining)

        return response.json()

    def _get_api_game_slug(self, game_slug: str) -> str:
        """[NEW] Unified slug conversion for PandaScore endpoints"""
        if game_slug == "league-of-legends":
            return "lol"
        return game_slug.replace("-", "_") if "-" in game_slug else game_slug

    async def _fetch_running_matches(self) -> List[dict]:
        """Fetch currently running matches for all enabled games globally"""
        try:
            # GET /matches/running returns all ongoing matches across all games
            matches = await self._fetch("/matches/running", {"per_page": 100})
            
            enabled_games = {slug for slug, config in GAME_REGISTRY.items() if config.get("enabled", True)}
            
            filtered_matches = []
            for m in matches:
                vg_slug = m.get("videogame", {}).get("slug")
                # Normalize 'lol' to 'league-of-legends' for internal consistency
                internal_slug = "league-of-legends" if vg_slug == "lol" else vg_slug
                
                if internal_slug in enabled_games:
                    m["_videogame"] = internal_slug
                    filtered_matches.append(m)
            
            return filtered_matches
        except Exception as e:
            logger.error(f"Failed to fetch global running matches: {e}")
            return []

    async def _fetch_match_by_id(self, match_id: int) -> Optional[dict]:
        """Fetch single match details"""
        try:
            matches = await self._fetch(f"/matches/{match_id}")
            return matches if isinstance(matches, dict) else None
        except Exception as e:
            logger.error(f"Failed to fetch match {match_id}: {e}")
            return None

    def _update_esports_cache(self, db: Session, api_matches: List[dict]):
        """Update EsportsMatch cache from API data"""
        running_ids: Set[int] = set()
        pending_notifications = []  # Collect notifications to send after commit

        for m in api_matches:
            match_id = m.get("id")
            if not match_id:
                continue
            running_ids.add(match_id)

            existing = db.query(EsportsMatch).filter(EsportsMatch.match_id == match_id).first()
            if existing:
                # [FIXED] Idempotent start notification
                if existing.status == "not_started" and not existing.start_notified_at:
                    existing.start_notified_at = utcnow()
                    pending_notifications.append({
                        "type": "start",
                        "match_id": match_id,
                        "videogame": existing.videogame,
                        "name": existing.name,
                        "stream_url": m.get('official_stream_url')
                    })
                
                existing.status = "running"
                existing.last_seen_running_at = utcnow()
                existing.missing_count = 0
            else:
                # New running match discovered
                videogame = m.get("_videogame", m.get("videogame", {}).get("slug"))
                name = m.get("name")
                new_match = EsportsMatch(
                    match_id=match_id,
                    league_id=m.get("league", {}).get("id"),
                    serie_id=m.get("serie", {}).get("id"),
                    tournament_id=m.get("tournament", {}).get("id"),
                    videogame=videogame,
                    name=name,
                    status="running",
                    scheduled_at=self._parse_datetime(m.get("scheduled_at")),
                    begin_at=self._parse_datetime(m.get("begin_at")),
                    last_seen_running_at=utcnow(),
                    missing_count=0,
                    start_notified_at=utcnow(),  # Mark as notified immediately
                )
                db.add(new_match)
                pending_notifications.append({
                    "type": "start",
                    "match_id": match_id,
                    "videogame": videogame,
                    "name": name,
                    "stream_url": m.get('official_stream_url')
                })
        
        # Return both running IDs and pending notifications
        return running_ids, pending_notifications

    def _parse_datetime(self, iso_str: Optional[str]) -> Optional[datetime]:
        """Parse ISO datetime string to naive UTC datetime"""
        if not iso_str:
            return None
        # Convert aware UTC to naive UTC to match system behavior
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    async def _check_missing_matches(self, db: Session, current_running_ids: Set[int]):
        """Check matches that were running but are no longer in the list"""
        # Find matches we think are running but aren't in the current API response
        db_running = db.query(EsportsMatch).filter(
            EsportsMatch.status == "running"
        ).all()

        for match in db_running:
            if match.match_id in current_running_ids:
                continue

            # Match is missing from running list
            match.missing_count += 1
            logger.info(f"Match {match.match_id} missing from running (count: {match.missing_count})")

            if match.missing_count >= MISSING_THRESHOLD:
                # Double-check confirmed, fetch actual status
                await self._confirm_match_status(db, match)

    async def _confirm_match_status(self, db: Session, match: EsportsMatch):
        """Confirm a match's actual status after it disappeared from running"""
        api_match = await self._fetch_match_by_id(match.match_id)
        if not api_match:
            logger.warning(f"Could not fetch match {match.match_id} for confirmation")
            return

        new_status = api_match.get("status")
        logger.info(f"[{match.videogame}] Match {match.name} ({match.match_id}) status updated to {new_status}")

        if new_status == "running":
            # Ghost disappearance, reset
            match.missing_count = 0
            match.last_seen_running_at = utcnow()
        elif new_status == "finished":
            match.status = "finished"
            match.end_at = self._parse_datetime(api_match.get("end_at"))
            await self._on_match_finished(db, match, api_match)
        elif new_status in ("canceled", "postponed", "rescheduled"):
            match.status = new_status
            # Optionally notify about cancellation/postponement
        else:
            match.status = new_status

    async def _on_match_finished(self, db: Session, match: EsportsMatch, api_data: dict):
        """Handle match finished event - notify and find next match"""
        await notify_match_finished(match, api_data, self.dry_run)
        
        # Find and notify next match
        next_match = await notify_next_match(db, match)
        if next_match:
            match.next_match_id = next_match.match_id

    async def _index_upcoming_matches(self, db: Session):
        """Index upcoming matches to cache and handle pre-match notifications"""
        now = utcnow()
        pre_match_threshold = now + timedelta(minutes=10)

        for game_slug, config in GAME_REGISTRY.items():
            if not config.get("enabled", True):
                continue
            try:
                api_game = self._get_api_game_slug(game_slug)
                matches = await self._fetch(
                    f"/{api_game}/matches/upcoming",
                    {"per_page": 10, "sort": "begin_at"}  # ~3-4 upcoming matches per day per game
                )

                for m in matches:
                    match_id = m.get("id")
                    if not match_id:
                        continue
                    
                    match_game_slug = game_slug
                    league_name = (m.get("league") or {}).get("name") or ""
                    
                    # [NEW] Strict League Filtering Logic
                    is_valid_league = False
                    
                    if match_game_slug == "league-of-legends":
                        # Allow LCK (covers LCK CL), LPL, and International Events (2026 Season)
                        allowed_lol = [
                            'LCK', 'LPL', 
                            'First Stand', 'First-Stand',
                            'MSI', 'Mid-Season Invitational', 
                            'Worlds', 'World Championship', 
                            'Esports World Cup', 'EWC'
                        ]
                        is_valid_league = any(word in league_name for word in allowed_lol)
                        
                    elif match_game_slug == "valorant":
                        # Block Tier 2
                        if 'Challengers' in league_name or 'VCL' in league_name:
                            is_valid_league = False
                        else:
                            # Allow Tier 1
                            allowed_vct = ['VCT', 'Champions', 'Masters']
                            is_valid_league = any(word in league_name for word in allowed_vct)
                    else:
                        # Default fallback for other games (e.g. PUBG)
                        # Check exclude keywords from config
                        exclude_kws = config.get("exclude_keywords", [])
                        is_valid_league = not any(kw.lower() in league_name.lower() for kw in exclude_kws)

                    if not is_valid_league:
                        continue

                    existing = db.query(EsportsMatch).filter(EsportsMatch.match_id == match_id).first()
                    if not existing:
                        existing = EsportsMatch(
                            match_id=match_id,
                            league_id=m.get("league", {}).get("id"),
                            serie_id=m.get("serie", {}).get("id"),
                            tournament_id=m.get("tournament", {}).get("id"),
                            videogame=game_slug,
                            name=m.get("name"),
                            status="not_started",
                            scheduled_at=self._parse_datetime(m.get("scheduled_at") or m.get("begin_at")),
                        )
                        db.add(existing)
                    else:
                        # Update scheduled time if changed
                        new_scheduled = self._parse_datetime(m.get("scheduled_at") or m.get("begin_at"))
                        if new_scheduled and existing.scheduled_at != new_scheduled:
                            existing.scheduled_at = new_scheduled

                    # [NEW] Pre-match Notification (10 min before)
                    if existing.status == "not_started" and existing.scheduled_at:
                        if now <= existing.scheduled_at <= pre_match_threshold:
                            if not existing.imminent_notified_at:
                                asyncio.create_task(notify_pre_match(
                                    match_id=match_id,
                                    name=existing.name,
                                    scheduled_at=existing.scheduled_at,
                                    videogame=game_slug
                                ))
                                existing.imminent_notified_at = now

            except Exception as e:
                logger.warning(f"Failed to index upcoming for {game_slug}: {e}")

        db.commit()
        logger.info("Upcoming matches indexed")

    async def _cleanup_old_matches(self, db: Session):
        """[NEW] 7일 이상 지난 과거 경기 기록을 삭제하여 DB 비대화 방지"""
        try:
            threshold = utcnow() - timedelta(days=7)
            # [FIXED] Handle matches without end_at by using scheduled_at as fallback
            deleted = db.query(EsportsMatch).filter(
                (EsportsMatch.status.in_(["finished", "canceled", "postponed"])) &
                ((EsportsMatch.end_at < threshold) | (EsportsMatch.scheduled_at < threshold))
            ).delete(synchronize_session=False)
            
            if deleted > 0:
                db.commit()
                logger.info(f"Cleanup: Deleted {deleted} old esports matches (older than 7 days)")
        except Exception as e:
            logger.error(f"Failed to cleanup old esports matches: {e}")
            db.rollback()

    async def run_running_watcher(self):
        """Main loop: watch for running matches"""
        logger.info("Starting Running Watcher...")

        # [FIXED] Initialize with aware datetime to prevent TypeError
        last_upcoming_index = utcnow() - timedelta(seconds=UPCOMING_INDEX_INTERVAL + 1)
        
        while self.running:
            db = SessionLocal()
            try:
                # Determine interval
                interval = self._get_poll_interval(db)
                current_kst = now_kst()
                is_active = self._is_in_active_window(current_kst) or self._has_imminent_match(db)
                logger.debug(f"Active Window: {is_active}, Polling Interval: {interval}s")

                # [FIXED] Only monitor running matches during active windows or when a match is imminent
                if is_active:
                    # Fetch running matches
                    running_matches = await self._fetch_running_matches()
                    running_ids, pending_notifications = self._update_esports_cache(db, running_matches)
                    db.commit()
                    
                    # Send notifications AFTER commit succeeds
                    for notif in pending_notifications:
                        if notif["type"] == "start":
                            asyncio.create_task(notify_match_start(
                                match_id=notif["match_id"],
                                videogame=notif["videogame"],
                                name=notif["name"],
                                stream_url=notif["stream_url"]
                            ))

                    # Check for matches that disappeared
                    await self._check_missing_matches(db, running_ids)
                    db.commit()
                else:
                    logger.debug("Outside active window. Skipping running matches check.")

                # Periodically index upcoming
                if (utcnow() - last_upcoming_index).total_seconds() > UPCOMING_INDEX_INTERVAL:
                    await self._index_upcoming_matches(db)
                    await self._cleanup_old_matches(db)
                    last_upcoming_index = utcnow()

            except Exception as e:
                logger.exception(f"Error in Running Watcher: {e}")
                db.rollback()
            finally:
                db.close()

            await asyncio.sleep(interval)

    async def start(self):
        """Start the monitor"""
        if not self.api_key:
            logger.error("PANDASCORE_API_KEY not set. Cannot start monitor.")
            return

        self.running = True
        logger.info(f"EsportsMonitor starting (dry_run={self.dry_run})")

        try:
            await self.run_running_watcher()
        finally:
            if self._client:
                await self._client.aclose()
            self.running = False

    def stop(self):
        """Stop the monitor"""
        self.running = False
        logger.info("EsportsMonitor stopped")


async def run_esports_monitor(dry_run: bool = False):
    """Entry point for the esports monitor"""
    monitor = EsportsMonitor(dry_run=dry_run)
    await monitor.start()
