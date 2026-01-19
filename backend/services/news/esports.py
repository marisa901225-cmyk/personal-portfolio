import logging
import httpx
import asyncio
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from ...core.models import GameNews
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

def get_display_league_tag(m: dict) -> str:
    """
    발로란트 대회의 경우 구체적인 시리즈/토너먼트 이름을 반환한다.
    우선순위: Tournament Name > Serie Name > League Name
    """
    league = (m.get("league") or {}).get("name")
    serie = (m.get("serie") or {}).get("full_name") or (m.get("serie") or {}).get("name")
    tour = (m.get("tournament") or {}).get("name")
    
    # 너무 긴 이름은 적당히 잘라내거나 조정할 수 있음, 여기서는 serie나 tour 우선 사용
    # 보통 VCT 2026: EMEA Kickoff 형태가 serie full_name에 들어옴.
    if serie:
        return serie
    if tour:
        return tour
    return league or "Valorant"

def is_noise(m: dict) -> bool:
    """
    원치 않는 하위 리그나 이벤트성 매치를 필터링한다 (True면 노이즈)
    """
    t = " ".join([
        str((m.get("league") or {}).get("name") or ""),
        str((m.get("serie") or {}).get("full_name") or (m.get("serie") or {}).get("name") or ""),
        str((m.get("tournament") or {}).get("name") or ""),
    ]).lower()
    
    # 제외 키워드 목록
    noise_keywords = [
        "game changers", "gc ", "gc-", "monthly", "qualifier", "showmatch", 
        "challengers", "division", "open", "premier", "ascension", "trials"
    ]
    
    if any(k in t for k in noise_keywords):
        return True
        
    return False

async def fetch_with_retry(client: httpx.AsyncClient, url: str, headers: dict, params: dict, max_retries: int = 3) -> httpx.Response:
    """
    429 rate limit 대응을 포함한 재시도 로직
    """
    for attempt in range(max_retries):
        try:
            response = await client.get(url, headers=headers, params=params, timeout=20.0)
            
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", "60"))
                logger.warning(f"Rate limited (429), waiting {retry_after}s... (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(retry_after)
                continue
            
            response.raise_for_status()
            return response
            
        except httpx.HTTPStatusError as e:
            if attempt == max_retries - 1:
                raise
            logger.warning(f"HTTP error {e.response.status_code}, retrying... (attempt {attempt + 1}/{max_retries})")
            await asyncio.sleep(2 ** attempt)  # exponential backoff
            
    raise Exception(f"Max retries ({max_retries}) exceeded")

async def cleanup_old_schedules(db: Session):
    """
    7일 이상 지난 과거 e스포츠 일정을 삭제한다.
    """
    try:
        # event_time은 tzinfo 없이 KST 기준으로 저장되므로 KST 기준으로 threshold 계산
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
    
    api_key = os.getenv("PANDASCORE_API_KEY")
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

        interest_keywords = [
            "lck", "lpl", "lec", "lcs", "worlds", "msi", "월즈",
            "challengers", "cl", "pacific", "vct", "masters", "champions",
        ]
        exclude_keywords = [".a", "academy", "youth", "secondary", "아카데미"]

        count = 0
        for match in matches:
            name = match.get("name", "")
            game_info = match.get("videogame", {})
            game_name = game_info.get("name", "").lower()
            league = match.get("league", {}).get("name", "Unknown League")
            begin_at_str = match.get("begin_at")
            if not begin_at_str: 
                continue

            # 종목 필터링 (API에서 game_name이 'LoL' 또는 'League of Legends'로 올 수 있음)
            is_lol = game_name in ("lol", "league of legends")
            is_valorant = "valorant" == game_name
            if not (is_lol or is_valorant):
                continue
            
            # 노이즈 필터링 (Game Changers 등)
            if is_valorant and is_noise(match):
                # logger.debug(f"Skipping noise match: {name} ({match.get('league', {}).get('name')})")
                continue

            game_tag = "LoL" if is_lol else "Valorant"
            
            # UTC aware datetime으로 파싱 및 저장
            begin_at_utc = parse_ps_datetime_utc(begin_at_str)
            begin_at_kst = to_kst(begin_at_utc)

            # 리그 태깅
            league_name = match.get("league", {}).get("name") or ""
            league_tag = "기타"
            is_international = False
            
            lower_league = league_name.lower()
            
            if is_valorant:
                # 발로란트는 구체적인 대회명을 태그로 사용
                league_tag = get_display_league_tag(match)
                # 국제 대회 여부 판단 (키워드 기반)
                if any(kw in league_tag.lower() for kw in ["champions", "masters", "kickoff", "ascension"]):
                    is_international = True
            elif "lck" in lower_league:
                league_tag = "LCK"
                if any(kw in lower_league for kw in ["challengers", "cl"]):
                    league_tag = "LCK-CL"
            elif "lpl" in lower_league:
                league_tag = "LPL"
            elif "lec" in lower_league:
                league_tag = "LEC"
            elif "lcs" in lower_league:
                league_tag = "LCS"
            elif any(kw in lower_league for kw in ["worlds", "msi", "mid-season invitational"]):
                league_tag = "Worlds/MSI"
                is_international = True
            elif any(kw in lower_league for kw in ["champions", "masters", "vct"]):
                league_tag = "VCT"
                is_international = True

            # 관심 리그 필터링
            # 발로란트는 필터링 통과 (이미 noise 체크 함), LoL은 기존 로직 유지
            full_text = f"{name} {league}".lower()
            
            if is_valorant:
                # 발로란트: VCT 메인 및 주요 대회(Champions, Masters, Kickoff)만 관심 경기로 인정
                vct_main_keywords = ["vct", "champions", "masters", "kickoff"]
                is_interesting = any(kw in league_tag.lower() for kw in vct_main_keywords)
            else:
                is_interesting = (league_tag != "기타") or any(kw in full_text for kw in interest_keywords)
            
            is_lck_cl = any(kw in full_text for kw in ["lck", "challengers", "cl"])
            is_academy = any(ex in full_text for ex in exclude_keywords)
            
            if not is_interesting:
                continue
            if is_academy and not is_lck_cl:
                continue
            
            title = f"[Esports Schedule] {game_tag} - {name}"
            # content에 KST 시간 포함 (사용자 가독성)
            content = (
                f"Match: {name}\n"
                f"League: {league}\n"
                f"Tournament: {match.get('tournament', {}).get('name')}\n"
                f"Start Time (KST): {begin_at_kst.strftime('%Y-%m-%d %H:%M')}\n"
                f"Start Time (UTC): {begin_at_utc.strftime('%Y-%m-%d %H:%M')}\n"
                f"Link: {match.get('official_stream_url') or ''}"
            )
            
            content_hash = calculate_simhash(title + content)
            existing = db.query(GameNews).filter(GameNews.content_hash == content_hash).first()
            if existing: 
                continue

            # DB에는 KST naive로 저장 (SQLite tz 처리 안정성)
            news = GameNews(
                content_hash=content_hash,
                game_tag=game_tag,
                league_tag=league_tag,
                is_international=is_international,
                source_name="PandaScore",
                source_type="schedule",
                # SQLite에서 tz-aware datetime 저장/비교가 불안정하므로 UTC naive로 저장
                event_time=begin_at_utc.replace(tzinfo=None),
                title=title,
                full_content=content,
                published_at=datetime.utcnow()
            )
            db.add(news)
            count += 1

        db.commit()
        logger.info(f"Collected {count} PandaScore match schedules.")
        
        # 챌린저스 비중계 결과 수집
        await collect_pandascore_results(db)
        
    except Exception as e:
        logger.error(f"Failed to collect PandaScore schedules: {e}")
        db.rollback()

async def collect_pandascore_results(db: Session):
    """
    최근 종료된 경기 결과를 수집하고, LCK 챌린저스 비중계일(수,목,금)인 경우 알림을 보낸다.
    """
    api_key = os.getenv("PANDASCORE_API_KEY")
    if not api_key:
        logger.warning("PANDASCORE_API_KEY not set for results collection.")
        return
        
    url = f"{PANDASCORE_URL}/matches/past"
    headers = {"Authorization": f"Bearer {api_key}"}
    
    try:
        async with httpx.AsyncClient() as client:
            # 429 대응 포함
            resp = await fetch_with_retry(
                client, url, headers, 
                {"per_page": 20, "sort": "-id", "filter[videogame]": "league-of-legends"}
            )
            matches = resp.json()
            
        results_to_notify = []
        for m in matches:
            league_name = m.get("league", {}).get("name") or ""
            if "CHALLENGERS" not in league_name.upper(): 
                continue
            if m.get("status") != "finished": 
                continue
            
            begin_at_str = m.get("begin_at")
            if not begin_at_str: 
                continue
            
            begin_at_utc = parse_ps_datetime_utc(begin_at_str)
            begin_at_kst = to_kst(begin_at_utc)
            
            # 비중계일 체크 (수=2, 목=3, 금=4) - KST 기준
            if begin_at_kst.weekday() not in [2, 3, 4]:
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

        # 알림 재전송 방지: 먼저 DB 커밋 → 그 다음 텔레그램 전송
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
                notified_at=datetime.utcnow(), # 알림 전송 시각 저장 (LO의 추천 💖)
                published_at=datetime.utcnow()
            )
            db.add(news)
        
        db.commit()  # 먼저 커밋
        logger.info(f"Committed {len(results_to_notify)} LCK-CL results to DB.")
        
        # 커밋 후 텔레그램 전송 (실패해도 중복 방지됨)
        from ...integrations.telegram import send_telegram_message
        lines = ["🏆 <b>[LCK-CL 비중계 경기 결과]</b>\n중계 없는 날도 챙겨왔어! ❤️\n"]
        for r in results_to_notify:
            lines.append(f"<b>{r['name']}</b>")
            lines.append(f"결과: {r['winner']} 승리 ({r['score']})")
            lines.append(f"시간: {r['time_kst'].strftime('%m/%d %H:%M')} KST\n")
        
        await send_telegram_message("\n".join(lines))
        logger.info(f"Sent {len(results_to_notify)} LCK-CL result notifications.")
        
    except Exception as e:
        logger.error(f"Error in collect_pandascore_results: {e}")
        db.rollback()
