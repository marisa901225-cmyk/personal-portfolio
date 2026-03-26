import logging
import httpx
import asyncio
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from ...core.models import GameNews
from ..llm_service import LLMService
from .core import calculate_simhash, STEAMSPY_URL
from ..duckdb_refine_config import get_db_path

logger = logging.getLogger(__name__)
_KST = ZoneInfo("Asia/Seoul")
_STEAM_RANKING_TITLE_RE = re.compile(r"^\[Steam Ranking\]\s*(?P<name>.+)$")
_STEAM_RANK_RE = re.compile(r"(?im)^Rank:\s*(?P<rank>\d+)\s*$")
_STEAM_OWNERS_RE = re.compile(r"(?im)^Owners:\s*(?P<owners>.+)\s*$")


def _extract_game_name(title: str) -> str:
    match = _STEAM_RANKING_TITLE_RE.match(str(title or "").strip())
    if match:
        return match.group("name").strip()
    return str(title or "").strip()


def _extract_rank(content: str) -> int | None:
    match = _STEAM_RANK_RE.search(str(content or ""))
    if not match:
        return None
    try:
        return int(match.group("rank"))
    except (TypeError, ValueError):
        return None


def _extract_owners(content: str) -> str:
    match = _STEAM_OWNERS_RE.search(str(content or ""))
    if not match:
        return ""
    return match.group("owners").strip()


def _parse_dt(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_KST)


def load_monthly_steam_ranking_summary(
    *,
    db_path: str | None = None,
    now: datetime | None = None,
    lookback_days: int = 30,
    top_games: int = 5,
) -> str:
    """
    최근 SteamSpy 랭킹 스냅샷을 월간 맥락으로 압축한다.

    최근 30일 데이터가 없으면 가장 최신 스냅샷을 참고용으로 반환한다.
    """
    db_file = db_path or get_db_path()
    if not db_file or not Path(db_file).exists():
        return ""

    now_kst = now or datetime.now(_KST)
    if now_kst.tzinfo is None:
        now_kst = now_kst.replace(tzinfo=_KST)
    else:
        now_kst = now_kst.astimezone(_KST)

    since_kst = now_kst - timedelta(days=max(1, int(lookback_days)))
    since_str = since_kst.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    until_str = now_kst.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    limit = max(3, int(top_games))

    month_sql = """
        SELECT title, full_content, published_at
        FROM game_news
        WHERE source_name = 'SteamSpy'
          AND source_type = 'news'
          AND datetime(published_at) >= datetime(?)
          AND datetime(published_at) <= datetime(?)
        ORDER BY datetime(published_at) DESC, id ASC
        LIMIT 5000
    """
    latest_sql = """
        SELECT title, full_content, published_at
        FROM game_news
        WHERE source_name = 'SteamSpy'
          AND source_type = 'news'
        ORDER BY datetime(published_at) DESC, id ASC
        LIMIT 300
    """

    try:
        with sqlite3.connect(db_file) as conn:
            cur = conn.cursor()
            rows = list(cur.execute(month_sql, (since_str, until_str)))
            is_fallback = False
            if not rows:
                rows = list(cur.execute(latest_sql))
                is_fallback = True
    except Exception as exc:
        logger.error("Failed to load Steam monthly ranking summary: %s", exc, exc_info=True)
        return ""

    if not rows:
        return ""

    stats: dict[str, dict[str, object]] = {}
    snapshot_days: set[str] = set()
    latest_dt: datetime | None = None

    for title, full_content, published_at in rows:
        game_name = _extract_game_name(title)
        if not game_name:
            continue

        published_dt = _parse_dt(published_at)
        if published_dt:
            snapshot_days.add(published_dt.strftime("%Y-%m-%d"))
            if latest_dt is None or published_dt > latest_dt:
                latest_dt = published_dt

        item = stats.setdefault(
            game_name,
            {
                "count": 0,
                "latest_dt": None,
                "latest_rank": None,
                "owners": "",
            },
        )
        item["count"] = int(item["count"]) + 1

        rank = _extract_rank(full_content)
        owners = _extract_owners(full_content)
        prev_latest = item.get("latest_dt")
        if published_dt and (prev_latest is None or published_dt >= prev_latest):
            item["latest_dt"] = published_dt
            item["latest_rank"] = rank
            item["owners"] = owners

    if not stats:
        return ""

    ranked_games = sorted(
        stats.items(),
        key=lambda pair: (
            -int(pair[1]["count"]),
            10_000 if pair[1]["latest_rank"] is None else int(pair[1]["latest_rank"]),
            pair[0].lower(),
        ),
    )

    lines: list[str] = []
    for game_name, meta in ranked_games[:limit]:
        details: list[str] = [f"{int(meta['count'])}회 포착"]
        if meta.get("latest_rank") is not None:
            details.append(f"최신 #{int(meta['latest_rank'])}")
        owners = str(meta.get("owners") or "").strip()
        if owners:
            details.append(f"보유자 {owners}")
        lines.append(f"{game_name}({', '.join(details)})")

    latest_label = latest_dt.strftime("%Y-%m-%d %H:%M KST") if latest_dt else "시각미상"
    snapshot_count = max(1, len(snapshot_days))

    if is_fallback:
        return (
            f"최근 {max(1, int(lookback_days))}일 Steam 월간 데이터는 비어 있음. "
            f"최신 Steam 인기게임 스냅샷({latest_label}, 참고용): "
            + "; ".join(lines)
        )

    return (
        f"최근 {max(1, int(lookback_days))}일 Steam 인기게임 월간 흐름"
        f"(수집일 {snapshot_count}회, 최신 {latest_label}): "
        + "; ".join(lines)
    )

async def collect_steamspy_rankings(db: Session):
    """
    SteamSpy API를 사용하여 최근 2주간 인기 게임 순위를 수집한다.
    """
    logger.info("Collecting SteamSpy popular games (top 100 in 2 weeks)...")
    params = {"request": "top100in2weeks"}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(STEAMSPY_URL, params=params, timeout=20.0)
            response.raise_for_status()
            data = response.json()

        count = 0
        now_utc = datetime.now(timezone.utc)
        kst_now = now_utc.astimezone(_KST)
        day_start_kst = kst_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end_kst = day_start_kst + timedelta(days=1)
        day_start_utc = day_start_kst.astimezone(timezone.utc)
        day_end_utc = day_end_kst.astimezone(timezone.utc)

        for rank, (appid, info) in enumerate(data.items(), start=1):
            name = info.get("name", "Unknown Game")
            owners = info.get("total_owners", info.get("owners", "Unknown Owners"))
            price = info.get("price", "0")
            if price == "0" or price == 0:
                price_str = "Free"
            else:
                price_str = f"${float(price)/100:.2f}"

            title = f"[Steam Ranking] {name}"
            content = (
                f"Rank: {rank}\n"
                f"Game: {name}\n"
                f"AppID: {appid}\n"
                f"Developer: {info.get('developer')}\n"
                f"Publisher: {info.get('publisher')}\n"
                f"Price: {price_str}\n"
                f"Owners: {owners}\n"
                f"Positive/Negative: {info.get('positive')}/{info.get('negative')}"
            )
            
            content_hash = calculate_simhash(title + content)
            existing = db.query(GameNews.id).filter(
                GameNews.source_name == "SteamSpy",
                GameNews.title == title,
                GameNews.published_at >= day_start_utc,
                GameNews.published_at < day_end_utc,
            ).first()
            if existing:
                continue

            news = GameNews(
                content_hash=content_hash,
                game_tag="Steam",
                source_name="SteamSpy",
                source_type="news",
                title=title,
                url=f"https://store.steampowered.com/app/{appid}",
                full_content=content,
                published_at=now_utc,
            )
            db.add(news)
            count += 1
            
        db.commit()
        logger.info(f"Collected {count} SteamSpy ranking entries.")
    except Exception as e:
        logger.error(f"Failed to collect SteamSpy rankings: {e}")

async def collect_steam_new_trends(db: Session):
    """
    Steam Store의 신규 출시작 및 인기작을 수집하여 DB에 저장한다.
    """
    logger.info("Collecting Steam New Trends to DB...")
    url = "https://store.steampowered.com/api/featuredcategories/"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=20.0)
            response.raise_for_status()
            data = response.json()

        # 'new_releases'와 'top_sellers'에서 아이템 추출
        appids = []
        
        # 1. 신작 우선 추출
        new_releases = data.get("new_releases", {}).get("items", [])
        for item in new_releases[:5]: # 상위 5개
            appids.append(item.get("id"))
            
        # 2. 인기작 보충 (중복 제외)
        top_sellers = data.get("top_sellers", {}).get("items", [])
        for item in top_sellers:
            if len(appids) >= 10: break
            aid = item.get("id")
            if aid not in appids:
                appids.append(aid)

        if not appids:
            logger.warning("No trending AppIDs found on Steam Store.")
            return

        async with httpx.AsyncClient() as client:
            for aid in appids:
                # 상세 정보 조회 (한글 우선)
                detail_url = "https://store.steampowered.com/api/appdetails"
                res = await client.get(detail_url, params={"appids": aid, "l": "korean"}, timeout=10.0)
                if res.status_code == 200:
                    detail_data = res.json().get(str(aid), {})
                    if detail_data.get("success"):
                        info = detail_data.get("data", {})
                        name = info.get("name")
                        desc = info.get("short_description", "")[:300]
                        genres = ", ".join([g.get("description") for g in info.get("genres", [])])
                        
                        # DB 저장 (중복 방지)
                        content = f"[장르: {genres}] {desc}"
                        title = f"[TREND] {name}"
                        content_hash = calculate_simhash(content)
                        
                        existing = db.query(GameNews.id).filter(
                            (GameNews.content_hash == str(content_hash)) | (GameNews.title == title)
                        ).first()
                        if not existing:
                            news = GameNews(
                                game_tag="Steam",
                                source_name="SteamStore",
                                source_type="trend",
                                title=f"[TREND] {name}",
                                url=f"https://store.steampowered.com/app/{aid}",
                                full_content=content,
                                content_hash=str(content_hash),
                                published_at=datetime.now(timezone.utc)
                            )
                            db.add(news)
                            db.commit()
                            logger.info(f"Saved Steam trend: {name}")
                
                await asyncio.sleep(0.5) # Rate limit 방지

        logger.info("Steam New Trends collection completed.")
        
    except Exception as e:
        logger.error(f"Failed to collect Steam trends: {e}")
