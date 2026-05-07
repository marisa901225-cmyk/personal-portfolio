import asyncio
import json
import logging
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from ...core.models import SteamPlayerSnapshot
from ..duckdb_refine_config import get_db_path
from .core import STEAMSPY_URL

logger = logging.getLogger(__name__)
_KST = ZoneInfo("Asia/Seoul")
_STEAM_FEATURED_CATEGORIES_URL = "https://store.steampowered.com/api/featuredcategories/"
_STEAM_STATS_URL = "https://store.steampowered.com/stats/stats/"
_STEAM_CURRENT_PLAYERS_URL = "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
_STEAM_STATS_ROW_RE = re.compile(
    r"(?P<current>[\d,]+).*?(?P<peak>[\d,]+).*?"
    r"store\.steampowered\.com/app/(?P<appid>\d+)[^>]*>\s*(?P<name>[^<]+)\s*</a>",
    re.IGNORECASE | re.DOTALL,
)
_STORE_BUCKETS = {"new_release", "top_seller", "sale", "watchlist"}
_RANKING_BUCKETS = {"official_top", "ranking"}
_STEAM_WATCHLIST_PATH = Path(__file__).resolve().parents[2] / "data" / "steam_trend_watchlist.json"


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


def _extract_appid_from_url(value: object) -> int:
    match = re.search(r"/app/(\d+)", str(value or ""))
    if not match:
        return 0
    return _safe_int(match.group(1))


def _load_steam_watchlist(path: str | Path | None = None) -> list[dict[str, object]]:
    watchlist_path = Path(path) if path else _STEAM_WATCHLIST_PATH
    if not watchlist_path.exists():
        return []

    try:
        payload = json.loads(watchlist_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Steam watchlist load failed path=%s error=%s", watchlist_path, exc)
        return []

    raw_items = payload.get("apps") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, object]] = []
    for raw in raw_items:
        if isinstance(raw, int):
            items.append({"appid": raw, "name": ""})
        elif isinstance(raw, str):
            appid = _safe_int(raw)
            if appid:
                items.append({"appid": appid, "name": ""})
        elif isinstance(raw, dict):
            appid = _safe_int(raw.get("appid") or raw.get("id"))
            if appid:
                items.append(
                    {
                        "appid": appid,
                        "name": str(raw.get("name") or "").strip(),
                        "thumbnail_url": str(raw.get("thumbnail_url") or raw.get("thumbnail") or "").strip(),
                    }
                )
    return items


def _parse_steam_stats_candidates(html_text: str, *, limit: int = 100) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for match in _STEAM_STATS_ROW_RE.finditer(str(html_text or "")):
        candidates.append(
            {
                "appid": _safe_int(match.group("appid")),
                "name": str(match.group("name") or "").strip(),
                "current_players": _safe_int(match.group("current")),
            }
        )
        if len(candidates) >= max(1, int(limit)):
            break
    return candidates


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
    """Steam 현재 접속자 시계열에서 스토어 화제작과 순위권 급등을 분리해 요약한다."""
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
        elif bucket in _RANKING_BUCKETS:
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
            "Steam 공식/SteamSpy 순위권 급등: "
            + "; ".join(_format_trending_entry(meta) for meta in ranking_items)
        )
    if not fragments:
        return ""

    latest_label = latest_dt.strftime("%Y-%m-%d %H:%M KST") if latest_dt else "시각미상"
    return f"Steam 실시간 접속자 트렌드(최신 {latest_label}): " + " | ".join(fragments)


async def collect_steam_player_snapshots(
    db: Session,
    *,
    official_limit: int = 100,
    ranking_limit: int = 100,
    store_limit: int = 40,
    watchlist_path: str | Path | None = None,
) -> int:
    """
    Steam 공식 통계, SteamSpy, Store 신작/할인/탑셀러, 관심 AppID의 현재 접속자 수를 저장한다.

    같은 AppID가 신작과 순위권 양쪽에 걸리면 양쪽 bucket으로 저장해서 브리핑에서 분리 계산한다.
    공식 통계 페이지에서 이미 현재 플레이어 수가 있는 항목은 그 값을 바로 저장해 API 호출을 줄인다.
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
        current_players: object | None = None,
    ) -> None:
        aid = _safe_int(appid)
        clean_name = str(name or "").strip()
        if aid <= 0:
            return
        if not clean_name:
            clean_name = f"Steam App {aid}"
        item = candidates.setdefault(
            aid,
            {
                "appid": aid,
                "name": clean_name,
                "store_url": _steam_store_url(aid),
                "thumbnail_url": str(thumbnail_url or "").strip(),
                "buckets": set(),
                "current_players_by_bucket": {},
            },
        )
        if clean_name and not str(clean_name).lower().startswith("steam app "):
            item["name"] = clean_name
        if thumbnail_url and not item.get("thumbnail_url"):
            item["thumbnail_url"] = str(thumbnail_url).strip()
        item["buckets"].add(bucket)
        current = _safe_int(current_players, default=-1)
        if current >= 0:
            item["current_players_by_bucket"][bucket] = current

    try:
        async with httpx.AsyncClient() as client:
            try:
                stats_response = await client.get(_STEAM_STATS_URL, timeout=20.0)
                stats_response.raise_for_status()
                for item in _parse_steam_stats_candidates(
                    stats_response.text,
                    limit=max(1, int(official_limit)),
                ):
                    _add_candidate(
                        item.get("appid"),
                        name=item.get("name"),
                        bucket="official_top",
                        current_players=item.get("current_players"),
                    )
            except Exception as exc:
                logger.warning("Steam official stats candidates failed: %s", exc)

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

                specials = store_data.get("specials", {}).get("items", [])
                sale_count = 0
                for item in specials:
                    if sale_count >= max(1, int(store_limit)):
                        break
                    aid = item.get("id") or item.get("appid") or _extract_appid_from_url(item.get("url"))
                    _add_candidate(
                        aid,
                        name=item.get("name"),
                        bucket="sale",
                        thumbnail_url=item.get("header_image") or item.get("small_capsule_image"),
                    )
                    sale_count += 1
            except Exception as exc:
                logger.warning("Steam Store trend candidates failed: %s", exc)

            for item in _load_steam_watchlist(watchlist_path):
                _add_candidate(
                    item.get("appid"),
                    name=item.get("name"),
                    bucket="watchlist",
                    thumbnail_url=item.get("thumbnail_url"),
                )

            if not candidates:
                logger.warning("No Steam player snapshot candidates found.")
                return 0

            count = 0
            for aid, meta in candidates.items():
                buckets = sorted(meta.get("buckets") or [])
                players_by_bucket = dict(meta.get("current_players_by_bucket") or {})
                missing_buckets = [bucket for bucket in buckets if bucket not in players_by_bucket]
                shared_current_players: int | None = None
                if missing_buckets:
                    try:
                        players_response = await client.get(
                            _STEAM_CURRENT_PLAYERS_URL,
                            params={"appid": aid},
                            timeout=10.0,
                        )
                        if players_response.status_code != 200:
                            continue
                        payload = players_response.json().get("response", {})
                        shared_current_players = _safe_int(payload.get("player_count"))
                    except Exception as exc:
                        logger.debug("Steam current players failed appid=%s error=%s", aid, exc)
                        continue

                for bucket in buckets:
                    current_players = _safe_int(
                        players_by_bucket.get(bucket),
                        default=shared_current_players if shared_current_players is not None else 0,
                    )
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
