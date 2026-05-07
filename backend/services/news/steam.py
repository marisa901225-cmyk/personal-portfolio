import logging
import httpx
import asyncio
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from ...core.models import GameNews, SteamPlayerSnapshot
from ..llm_service import LLMService
from .core import calculate_simhash, STEAMSPY_URL
from ..duckdb_refine_config import get_db_path

logger = logging.getLogger(__name__)
_KST = ZoneInfo("Asia/Seoul")
_STEAM_FEATURED_CATEGORIES_URL = "https://store.steampowered.com/api/featuredcategories/"
_STEAM_CURRENT_PLAYERS_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
_STEAM_RANKING_TITLE_RE = re.compile(r"^\[Steam Ranking\]\s*(?P<name>.+)$")
_STEAM_RANK_RE = re.compile(r"(?im)^Rank:\s*(?P<rank>\d+)\s*$")
_STEAM_OWNERS_RE = re.compile(r"(?im)^Owners:\s*(?P<owners>.+)\s*$")
_STORE_BUCKETS = {"new_release", "top_seller"}


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


def _rank_sort_value(meta: dict[str, object]) -> int:
    rank = meta.get("latest_rank")
    if rank is None:
        return 10_000
    return int(rank)


def _format_game_summary_entry(game_name: str, meta: dict[str, object]) -> str:
    details: list[str] = [f"{int(meta['count'])}회 포착"]
    if meta.get("latest_rank") is not None:
        details.append(f"최신 #{int(meta['latest_rank'])}")
    owners = str(meta.get("owners") or "").strip()
    if owners:
        details.append(f"보유자 {owners}")
    return f"{game_name}({', '.join(details)})"


def _pick_rank_band_games(
    ranked_games: list[tuple[str, dict[str, object]]],
    *,
    limit: int,
    exclude: set[str] | None = None,
    rank_min: int | None = None,
    rank_max: int | None = None,
) -> list[tuple[str, dict[str, object]]]:
    selected: list[tuple[str, dict[str, object]]] = []
    excluded_names = exclude or set()
    if limit <= 0:
        return selected

    for game_name, meta in ranked_games:
        if game_name in excluded_names:
            continue
        latest_rank = meta.get("latest_rank")
        if latest_rank is None and (rank_min is not None or rank_max is not None):
            continue
        if latest_rank is not None:
            rank_value = int(latest_rank)
            if rank_min is not None and rank_value < rank_min:
                continue
            if rank_max is not None and rank_value > rank_max:
                continue
        selected.append((game_name, meta))
        if len(selected) >= limit:
            break
    return selected


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


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


def _steam_store_url(appid: int) -> str:
    return f"https://store.steampowered.com/app/{appid}"


def _calculate_steam_trend_score(
    *,
    current_players: int,
    avg_7d: float,
    first_24h_players: int,
) -> float:
    current = max(0, int(current_players))
    if current <= 0:
        return 0.0

    seven_day_avg = max(1.0, float(avg_7d or 0.0))
    lift = max(0.0, (current / seven_day_avg) - 1.0)
    if lift <= 0:
        return 0.0

    first_24h = max(1, int(first_24h_players or 0))
    growth_24h = max(0.0, (current / first_24h) - 1.0)
    growth_factor = 1.0 + min(growth_24h, 3.0) * 0.35
    return math.log(current + 1) * lift * growth_factor


def _format_players(value: int) -> str:
    return f"{int(value):,}명"


def _format_trending_entry(meta: dict[str, object]) -> str:
    name = str(meta.get("name") or "").strip()
    current = _safe_int(meta.get("current_players"))
    peak_24h = _safe_int(meta.get("peak_24h"))
    avg_7d = float(meta.get("avg_7d") or 0.0)
    score = float(meta.get("trend_score") or 0.0)
    url = str(meta.get("store_url") or "").strip()
    parts = [
        f"현재 {_format_players(current)}",
        f"24h peak {_format_players(peak_24h)}",
        f"7일평균 {_format_players(round(avg_7d))}",
        f"score {score:.2f}",
    ]
    line = f"{name}({', '.join(parts)})"
    if url:
        line += f" {url}"
    return line


def load_steam_player_trending_summary(
    *,
    db_path: str | None = None,
    now: datetime | None = None,
    lookback_days: int = 7,
    store_limit: int = 5,
    ranking_limit: int = 5,
) -> str:
    """
    Steam 현재 접속자 시계열에서 신작/스토어 화제작과 SteamSpy 순위권을 분리해 요약한다.
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
    since_24h_kst = now_kst - timedelta(hours=24)
    since_str = since_kst.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    sql = """
        SELECT appid, name, source_bucket, current_players, store_url, thumbnail_url, captured_at
        FROM steam_player_snapshots
        WHERE datetime(captured_at) >= datetime(?)
        ORDER BY datetime(captured_at) ASC, id ASC
    """

    try:
        with sqlite3.connect(db_file) as conn:
            rows = list(conn.execute(sql, (since_str,)))
    except Exception as exc:
        logger.error("Failed to load Steam player trending summary: %s", exc, exc_info=True)
        return ""

    if not rows:
        return ""

    grouped: dict[tuple[int, str], dict[str, object]] = {}
    latest_dt: datetime | None = None
    for appid, name, bucket, players, store_url, thumbnail_url, captured_at in rows:
        captured_dt = _parse_dt(captured_at)
        if captured_dt is None:
            continue
        latest_dt = captured_dt if latest_dt is None or captured_dt > latest_dt else latest_dt
        key = (_safe_int(appid), str(bucket or "").strip() or "unknown")
        item = grouped.setdefault(
            key,
            {
                "appid": _safe_int(appid),
                "name": str(name or "").strip(),
                "source_bucket": str(bucket or "").strip(),
                "store_url": str(store_url or "").strip(),
                "thumbnail_url": str(thumbnail_url or "").strip(),
                "points": [],
            },
        )
        item["name"] = str(name or item["name"]).strip()
        item["store_url"] = str(store_url or item["store_url"]).strip()
        item["thumbnail_url"] = str(thumbnail_url or item["thumbnail_url"]).strip()
        item["points"].append((captured_dt, max(0, _safe_int(players))))

    sections: dict[str, list[dict[str, object]]] = {"store": [], "ranking": []}
    for item in grouped.values():
        points = list(item.get("points") or [])
        if not points:
            continue
        points.sort(key=lambda pair: pair[0])
        latest_point = points[-1]
        current = int(latest_point[1])
        avg_7d = sum(value for _, value in points) / max(1, len(points))
        points_24h = [(dt, value) for dt, value in points if dt >= since_24h_kst]
        if not points_24h:
            points_24h = [latest_point]
        first_24h_players = int(points_24h[0][1])
        peak_24h = max(value for _, value in points_24h)
        score = _calculate_steam_trend_score(
            current_players=current,
            avg_7d=avg_7d,
            first_24h_players=first_24h_players,
        )
        meta = {
            **item,
            "current_players": current,
            "avg_7d": avg_7d,
            "first_24h_players": first_24h_players,
            "peak_24h": peak_24h,
            "trend_score": score,
        }
        bucket = str(item.get("source_bucket") or "")
        if bucket in _STORE_BUCKETS:
            sections["store"].append(meta)
        elif bucket == "ranking":
            sections["ranking"].append(meta)

    def _sort_key(meta: dict[str, object]) -> tuple[float, int, str]:
        return (
            -float(meta.get("trend_score") or 0.0),
            -_safe_int(meta.get("current_players")),
            str(meta.get("name") or "").lower(),
        )

    def _dedupe_by_appid(items: list[dict[str, object]]) -> list[dict[str, object]]:
        selected: dict[int, dict[str, object]] = {}
        for meta in sorted(items, key=_sort_key):
            appid = _safe_int(meta.get("appid"))
            if appid not in selected:
                selected[appid] = meta
        return list(selected.values())

    store_items = _dedupe_by_appid(sections["store"])[: max(1, int(store_limit))]
    ranking_items = sorted(sections["ranking"], key=_sort_key)[: max(1, int(ranking_limit))]

    fragments: list[str] = []
    if store_items:
        fragments.append(
            "신작/스토어 화제작: "
            + "; ".join(_format_trending_entry(meta) for meta in store_items)
        )
    if ranking_items:
        fragments.append(
            "SteamSpy 순위권 급등: "
            + "; ".join(_format_trending_entry(meta) for meta in ranking_items)
        )
    if not fragments:
        return ""

    latest_label = latest_dt.strftime("%Y-%m-%d %H:%M KST") if latest_dt else "시각미상"
    return f"Steam 실시간 접속자 트렌드(최신 {latest_label}): " + " | ".join(fragments)


def load_monthly_steam_ranking_summary(
    *,
    db_path: str | None = None,
    now: datetime | None = None,
    lookback_days: int = 30,
    top_games: int = 5,
    middle_games: int | None = None,
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
    top_limit = max(3, int(top_games))
    middle_limit = max(2, int(middle_games if middle_games is not None else min(4, top_limit)))
    top_rank_max = 10
    middle_rank_min = 11
    middle_rank_max = 40

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
            _rank_sort_value(pair[1]),
            pair[0].lower(),
        ),
    )

    top_selection = _pick_rank_band_games(
        ranked_games,
        limit=top_limit,
        rank_max=top_rank_max,
    )
    selected_names = {game_name for game_name, _ in top_selection}
    if len(top_selection) < top_limit:
        top_selection.extend(
            _pick_rank_band_games(
                ranked_games,
                limit=top_limit - len(top_selection),
                exclude=selected_names,
            )
        )
        selected_names = {game_name for game_name, _ in top_selection}

    middle_selection = _pick_rank_band_games(
        ranked_games,
        limit=middle_limit,
        exclude=selected_names,
        rank_min=middle_rank_min,
        rank_max=middle_rank_max,
    )

    sections: list[str] = []
    if top_selection:
        sections.append(
            "상위권: " + "; ".join(
                _format_game_summary_entry(game_name, meta) for game_name, meta in top_selection
            )
        )
    if middle_selection:
        sections.append(
            "중위권: " + "; ".join(
                _format_game_summary_entry(game_name, meta) for game_name, meta in middle_selection
            )
        )
    if not sections:
        sections.append(
            "인기게임: " + "; ".join(
                _format_game_summary_entry(game_name, meta)
                for game_name, meta in ranked_games[:top_limit]
            )
        )

    latest_label = latest_dt.strftime("%Y-%m-%d %H:%M KST") if latest_dt else "시각미상"
    snapshot_count = max(1, len(snapshot_days))

    if is_fallback:
        return (
            f"최근 {max(1, int(lookback_days))}일 Steam 월간 데이터는 비어 있음. "
            f"최신 Steam 인기게임 스냅샷({latest_label}, 참고용): "
            + " | ".join(sections)
        )

    return (
        f"최근 {max(1, int(lookback_days))}일 Steam 인기게임 월간 흐름"
        f"(수집일 {snapshot_count}회, 최신 {latest_label}): "
        + " | ".join(sections)
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
    url = _STEAM_FEATURED_CATEGORIES_URL
    
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


async def collect_steam_player_snapshots(
    db: Session,
    *,
    ranking_limit: int = 40,
    store_limit: int = 20,
) -> int:
    """
    SteamSpy 순위권과 Steam Store 신작/탑셀러 후보의 현재 접속자 수를 저장한다.

    같은 AppID가 신작과 순위권 양쪽에 걸리면 양쪽 bucket으로 저장해서 브리핑에서 분리 계산한다.
    """
    logger.info("Collecting Steam current player snapshots...")
    captured_at = datetime.now(timezone.utc)
    candidates: dict[int, dict[str, object]] = {}

    def _add_candidate(
        appid: object,
        *,
        name: object,
        bucket: str,
        thumbnail_url: object = "",
    ) -> None:
        aid = _safe_int(appid)
        clean_name = str(name or "").strip()
        if aid <= 0 or not clean_name:
            return
        item = candidates.setdefault(
            aid,
            {
                "appid": aid,
                "name": clean_name,
                "store_url": _steam_store_url(aid),
                "thumbnail_url": str(thumbnail_url or "").strip(),
                "buckets": set(),
            },
        )
        item["name"] = clean_name or item["name"]
        if thumbnail_url and not item.get("thumbnail_url"):
            item["thumbnail_url"] = str(thumbnail_url).strip()
        item["buckets"].add(bucket)

    try:
        async with httpx.AsyncClient() as client:
            try:
                ranking_response = await client.get(
                    STEAMSPY_URL,
                    params={"request": "top100in2weeks"},
                    timeout=20.0,
                )
                ranking_response.raise_for_status()
                ranking_data = ranking_response.json()
                for idx, (appid, info) in enumerate(ranking_data.items()):
                    if idx >= max(1, int(ranking_limit)):
                        break
                    _add_candidate(appid, name=info.get("name"), bucket="ranking")
            except Exception as exc:
                logger.warning("SteamSpy ranking candidates failed: %s", exc)

            try:
                store_response = await client.get(_STEAM_FEATURED_CATEGORIES_URL, timeout=20.0)
                store_response.raise_for_status()
                store_data = store_response.json()

                new_releases = store_data.get("new_releases", {}).get("items", [])
                for item in new_releases[: max(1, min(10, int(store_limit)))]:
                    _add_candidate(
                        item.get("id"),
                        name=item.get("name"),
                        bucket="new_release",
                        thumbnail_url=item.get("header_image") or item.get("small_capsule_image"),
                    )

                top_sellers = store_data.get("top_sellers", {}).get("items", [])
                top_seller_count = 0
                for item in top_sellers:
                    if top_seller_count >= max(1, int(store_limit)):
                        break
                    _add_candidate(
                        item.get("id"),
                        name=item.get("name"),
                        bucket="top_seller",
                        thumbnail_url=item.get("header_image") or item.get("small_capsule_image"),
                    )
                    top_seller_count += 1
            except Exception as exc:
                logger.warning("Steam Store trend candidates failed: %s", exc)

            if not candidates:
                logger.warning("No Steam player snapshot candidates found.")
                return 0

            count = 0
            for aid, meta in candidates.items():
                try:
                    players_response = await client.get(
                        _STEAM_CURRENT_PLAYERS_URL,
                        params={"appid": aid},
                        timeout=10.0,
                    )
                    if players_response.status_code != 200:
                        continue
                    payload = players_response.json().get("response", {})
                    current_players = _safe_int(payload.get("player_count"))
                except Exception as exc:
                    logger.debug("Steam current players failed appid=%s error=%s", aid, exc)
                    continue

                for bucket in sorted(meta.get("buckets") or []):
                    db.add(
                        SteamPlayerSnapshot(
                            appid=aid,
                            name=str(meta.get("name") or ""),
                            source_bucket=str(bucket),
                            current_players=current_players,
                            store_url=str(meta.get("store_url") or _steam_store_url(aid)),
                            thumbnail_url=str(meta.get("thumbnail_url") or ""),
                            captured_at=captured_at,
                        )
                    )
                    count += 1
                await asyncio.sleep(0.15)

        db.commit()
        logger.info("Collected %s Steam current player snapshots.", count)
        return count
    except Exception as e:
        db.rollback()
        logger.error("Failed to collect Steam current player snapshots: %s", e, exc_info=True)
        return 0
