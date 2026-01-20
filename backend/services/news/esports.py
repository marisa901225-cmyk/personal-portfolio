import httpx
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log
from sqlalchemy.orm import Session
from ...core.config import settings
from ...core.models import GameNews
from ...core.time_utils import utcnow
from .core import calculate_simhash, PANDASCORE_URL

logger = logging.getLogger(__name__)

# 시간대 상수
KST = ZoneInfo("Asia/Seoul")

# Datetime 유틸리티
def parse_ps_datetime_utc(iso_z: str) -> datetime:
    """PandaScore ISO 문자열(Z)을 UTC aware datetime으로 변환"""
    return datetime.fromisoformat(iso_z.replace("Z", "+00:00")).astimezone(timezone.utc)

def to_kst(dt_utc: datetime) -> datetime:
    """UTC datetime을 KST로 변환"""
    return dt_utc.astimezone(KST)

from ...core.esports_config import GAME_REGISTRY, get_game_config

logger = logging.getLogger(__name__)

# 시간대 상수
KST = ZoneInfo("Asia/Seoul")

# Datetime 유틸리티
def parse_ps_datetime_utc(iso_z: str) -> datetime:
    """PandaScore ISO 문자열(Z)을 UTC aware datetime으로 변환"""
    return datetime.fromisoformat(iso_z.replace("Z", "+00:00")).astimezone(timezone.utc)

def to_kst(dt_utc: datetime) -> datetime:
    """UTC datetime을 KST로 변환"""
    return dt_utc.astimezone(KST)

def get_display_league_tag(m: dict, game_config: dict) -> str:
    """레지스트리 설정된 태거를 사용하여 리그 태그를 가져온다."""
    tagger = game_config.get("tagger")
    if tagger:
        return tagger(m)
    return (m.get("league") or {}).get("name") or "Unknown"

def is_noise(m: dict, game_config: dict) -> bool:
    """
    원치 않는 하위 리그나 이벤트성 매치를 필터링한다 (True면 노이즈)
    """
    t = " ".join([
        str((m.get("league") or {}).get("name") or ""),
        str((m.get("serie") or {}).get("full_name") or (m.get("serie") or {}).get("name") or ""),
        str((m.get("tournament") or {}).get("name") or ""),
    ]).lower()
    
    noise_keywords = game_config.get("noise_keywords") or []
    if any(k in t for k in noise_keywords):
        return True
        
    return False

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError)),
    before_sleep=before_sleep_log(logger, logging.WARNING)
)
async def fetch_with_retry(client: httpx.AsyncClient, url: str, headers: dict, params: dict) -> httpx.Response:
    """
    tenacity를 사용한 재시도 로직 (429 Rate Limit 및 서버 에러 대응)
    """
    response = await client.get(url, headers=headers, params=params, timeout=20.0)
    response.raise_for_status()
    return response

async def cleanup_old_schedules(db: Session):
    """
    7일 이상 지난 과거 e스포츠 일정을 삭제한다.
    """
    try:
        threshold_kst = datetime.now(KST).replace(tzinfo=None) - timedelta(days=7)
        
        deleted = db.query(GameNews).filter(
            GameNews.source_type == "schedule",
            GameNews.event_time < threshold_kst
        ).delete(synchronize_session=False)
        
        if deleted > 0:
            db.commit()
            logger.info(f"Cleanup: Deleted {deleted} old esports schedules (older than {threshold_kst}).")
    except Exception as e:
        logger.error(f"Failed to cleanup old esports schedules: {e}")
        db.rollback()

async def collect_pandascore_schedules(db: Session):
    """
    PandaScore API를 사용하여 향후 e스포츠 경기 일정을 수집한다.
    """
    await cleanup_old_schedules(db)
    
    api_key = settings.pandascore_api_key
    if not api_key:
        logger.warning("PANDASCORE_API_KEY not set. Skipping PandaScore collection.")
        return

    logger.info("Collecting PandaScore upcoming esports matches...")
    url = f"{PANDASCORE_URL}/matches/upcoming"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        matches = []
        per_page = 100
        max_pages = 5
        
        async with httpx.AsyncClient() as client:
            for page in range(1, max_pages + 1):
                params = {
                    "per_page": per_page, 
                    "page": page,
                    "sort": "begin_at"
                }
                
                response = await fetch_with_retry(client, url, headers, params)
                page_items = response.json()
                
                if not page_items:
                    break
                matches.extend(page_items)
                if len(page_items) < per_page:
                    break

        count = 0
        for match in matches:
            game_info = match.get("videogame", {})
            game_slug = game_info.get("slug", "").lower()
            
            # 레지스트리에서 게임 설정 가져오기
            game_config = get_game_config(game_slug)
            if not game_config:
                continue

            begin_at_str = match.get("begin_at")
            if not begin_at_str: 
                continue

            # 노이즈 필터링
            if is_noise(match, game_config):
                continue

            display_game_name = game_config["display_name"]
            
            begin_at_utc = parse_ps_datetime_utc(begin_at_str)
            begin_at_kst = to_kst(begin_at_utc)

            # 리그 태깅 및 국제 대회 여부
            league_tag = get_display_league_tag(match, game_config)
            is_international = False
            if "is_international" in game_config:
                is_international = game_config["is_international"](league_tag)

            # 관심 뉴스 여부 판단
            name = match.get("name", "")
            league_name = (match.get("league") or {}).get("name") or ""
            full_text = f"{name} {league_name} {league_tag}".lower()
            
            interest_keywords = game_config.get("interest_keywords") or []
            exclude_keywords = game_config.get("exclude_keywords") or []
            
            is_interesting = any(kw in full_text for kw in interest_keywords)
            is_excluded = any(ex in full_text for ex in exclude_keywords)
            
            if not is_interesting or is_excluded:
                continue
            
            title = f"[Esports Schedule] {display_game_name} - {name}"
            content = (
                f"Match: {name}\n"
                f"League: {league_name}\n"
                f"Tournament: {match.get('tournament', {}).get('name')}\n"
                f"Start Time (KST): {begin_at_kst.strftime('%Y-%m-%d %H:%M')}\n"
                f"Start Time (UTC): {begin_at_utc.strftime('%Y-%m-%d %H:%M')}\n"
                f"Link: {match.get('official_stream_url') or ''}"
            )
            
            content_hash = calculate_simhash(title + content)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing: 
                continue

            news = GameNews(
                content_hash=content_hash,
                game_tag=display_game_name,
                league_tag=league_tag,
                is_international=is_international,
                source_name="PandaScore",
                source_type="schedule",
                event_time=begin_at_utc.replace(tzinfo=None),
                title=title,
                full_content=content,
                published_at=utcnow()
            )
            db.add(news)
            count += 1

        db.commit()
        logger.info(f"Collected {count} PandaScore match schedules.")
        
        # 결과 수집 (현재는 LoL 챌린저스만 특화 처리됨)
        await collect_pandascore_results(db)
        
    except Exception as e:
        logger.error(f"Failed to collect PandaScore schedules: {e}")
        db.rollback()

async def collect_pandascore_results(db: Session):
    """
    최근 종료된 경기 결과를 수집하고, LCK 챌린저스 비중계일(수,목,금)인 경우 알림을 보낸다.
    (이 부분은 현재 LoL LCK-CL 전용 로직이므로 당분간 유지하거나 추후 더 일반화 가능)
    """
    api_key = settings.pandascore_api_key
    if not api_key:
        logger.warning("PANDASCORE_API_KEY not set for results collection.")
        return
        
    url = f"{PANDASCORE_URL}/matches/past"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await fetch_with_retry(
                client, url, headers, 
                {"per_page": 20, "sort": "-id", "filter[videogame]": "league-of-legends"}
            )
            matches = resp.json()
            
        results_to_notify = []
        for m in matches:
            league_name = (m.get("league") or {}).get("name") or ""
            if "CHALLENGERS" not in league_name.upper(): 
                continue
            if m.get("status") != "finished": 
                continue
            
            begin_at_str = m.get("begin_at")
            if not begin_at_str: 
                continue
            
            begin_at_utc = parse_ps_datetime_utc(begin_at_str)
            begin_at_kst = to_kst(begin_at_utc)
            
            # 비중계일 체크 (모든 요일 허용으로 변경하여 수집 누락 방지)
            if begin_at_kst.weekday() not in [0, 1, 2, 3, 4, 5, 6]: # 모든 요일 포함
                continue
            
            match_id = m.get("id")
            content_hash = f"RESULT_{match_id}"
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing: 
                continue
            
            name = m.get("name")
            winner = m.get("winner", {}).get("name") if m.get("winner") else "TBD"
            scores = [str(r.get("score")) for r in m.get("results", [])]
            score_text = " : ".join(scores) if scores else "0 : 0"
            
            results_to_notify.append({
                "hash": content_hash,
                "league": "LCK-CL",
                "name": name,
                "winner": winner,
                "score": score_text,
                "time_utc": begin_at_utc,
                "time_kst": begin_at_kst
            })

        if not results_to_notify: 
            return

        for r in results_to_notify:
            news = GameNews(
                content_hash=r["hash"],
                game_tag="LoL",
                league_tag="LCK-CL",
                source_name="PandaScore",
                source_type="result",
                event_time=r["time_kst"].replace(tzinfo=None),
                title=f"Result: {r['name']}",
                full_content=f"Winner: {r['winner']} ({r['score']})",
                notified_at=utcnow(),
                published_at=utcnow()
            )
            db.add(news)
        
        db.commit()
        logger.info(f"Committed {len(results_to_notify)} LCK-CL results to DB.")
        
        from ...integrations.telegram import send_telegram_message
        lines = ["🏆 <b>[LCK-CL 비중계 경기 결과]</b>\n중계 없는 날도 챙겨왔어! ❤️\n"]
        for r in results_to_notify:
            lines.append(f"<b>{r['name']}</b>")
            lines.append(f"결과: {r['winner']} 승리 ({r['score']})")
            lines.append(f"시간: {r['time_kst'].strftime('%m/%d %H:%M')} KST\n")
        
        await send_telegram_message("\n".join(lines))
        logger.info(f"Sent {len(results_to_notify)} LCK-CL result notifications.")
        
    except Exception:
        logger.exception("Error in collect_pandascore_results")
        db.rollback()
