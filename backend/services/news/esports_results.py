import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import httpx
from zoneinfo import ZoneInfo

from ...core.config import settings
from .core import PANDASCORE_URL

logger = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")


def _parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


async def _fetch(endpoint: str, params: Optional[dict] = None) -> Any:
    if not settings.pandascore_api_key:
        return None
    headers = {"Authorization": f"Bearer {settings.pandascore_api_key}"}
    url = f"{PANDASCORE_URL}{endpoint}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, headers=headers, params=params or {})
        res.raise_for_status()
        return res.json()


async def _get_league_id() -> Optional[int]:
    # 🌟 진짜 LEC ID: 4197 (League of Legends EMEA Championship)
    # 다른 종목이나 2021년 종료된 동명의 리그와 섞이지 않도록 LoL로 필터링
    try:
        leagues = await _fetch("/leagues", {
            "search[name]": "LEC", 
            "filter[videogame_id]": 1, # 1: League of Legends
            "per_page": 5
        })
        if isinstance(leagues, list) and leagues:
            # LoL 종목인 것만 찾기
            for l in leagues:
                if l.get("videogame", {}).get("slug") == "league-of-legends":
                    return l.get("id")
                    
        # Fallback to known good ID if search fails but we need LEC
        return 4197
    except Exception as e:
        logger.error("Failed to fetch LEC league id: %s", e)
    return 4197 # Hard fallback


def _format_match(match: Dict[str, Any], *, compact: bool = True) -> Optional[str]:
    opponents = match.get("opponents") or []
    results = match.get("results") or []
    winner = (match.get("winner") or {}).get("name")

    if len(opponents) >= 2:
        team_a = (opponents[0].get("opponent") or {}).get("name") or "TBD"
        team_b = (opponents[1].get("opponent") or {}).get("name") or "TBD"
        team_a_id = (opponents[0].get("opponent") or {}).get("id")
        team_b_id = (opponents[1].get("opponent") or {}).get("id")
        score_map = {
            r.get("team_id"): r.get("score")
            for r in results
            if r.get("team_id") is not None
        }
        score_a = score_map.get(team_a_id)
        score_b = score_map.get(team_b_id)

        if score_a is not None and score_b is not None:
            # 스코어가 0-0인 경우는 아직 시작 전이거나 무효한 데이터일 가능성이 높으므로 스킵 처리 유도
            if score_a == 0 and score_b == 0:
                return None
            base = f"{team_a} {score_a}-{score_b} {team_b}"
        else:
            # 스코어가 없으면 요약에서 제외 (브리핑 품질 목적)
            return None
    else:
        # 단일 상대거나 정보가 부족하면 제외
        return None

    if not compact:
        time_src = match.get("end_at") or match.get("begin_at")
        dt = _parse_iso(time_src)
        if dt:
            dt_kst = dt.astimezone(_KST)
            base = f"{base} ({dt_kst.strftime('%m/%d %H:%M')} KST)"

        if winner and winner not in base:
            base = f"{base} - 승리: {winner}"

    return base


async def fetch_lec_results_summary(
    limit: int = 10,
    lookback_hours: int = 48, # 저녁~새벽 경기를 아침에 수집하므로 48시간으로 넉넉하게 변경
    max_chars: int = 400, # 요약 가독성을 위해 글자수 제한 상향
) -> str:
    """
    LEC 최근 경기 결과를 간단히 요약합니다.
    """
    if not settings.pandascore_api_key:
        return ""

    league_id = await _get_league_id()
    if not league_id:
        return ""

    try:
        # 🌟 LO의 똑똑한 제안: /lol/matches/past 엔드포인트 사용
        # 이 엔드포인트는 이미 끝난 경기들만 최신순으로 반환하므로 훨씬 효율적임
        # 하지만 간혹 0-0 상태의 경기가 섞여 나올 수 있으므로 필터링 필요
        matches = await _fetch(
            "/lol/matches/past",
            {
                "filter[league_id]": league_id,
                "sort": "-end_at", # 최근에 끝난 순서대로
                "per_page": max(10, limit * 2), # 필터링을 고려하여 넉넉하게 가져옴
            },
        )
    except Exception as e:
        logger.error("Failed to fetch LEC matches: %s", e)
        return ""

    if not isinstance(matches, list) or not matches:
        return ""

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(hours=lookback_hours)

    lines: List[str] = []
    for m in matches:
        time_src = m.get("end_at") or m.get("begin_at")
        dt = _parse_iso(time_src)
        
        # 48시간 이내 경기만 포함
        if dt and dt < cutoff:
            continue

        line = _format_match(m, compact=True)
        if line:
            lines.append(line)
        if len(lines) >= limit:
            break

    if not lines:
        return ""

    joined = "최근 LEC 경기 결과: " + " | ".join(lines)
    if max_chars and len(joined) > max_chars:
        # Cut at a separator boundary if possible.
        truncated = joined[:max_chars]
        cut = truncated.rfind(" | ")
        if cut >= 0:
            truncated = truncated[:cut]
        joined = truncated.rstrip() + " ..."
    return joined


__all__ = ["fetch_lec_results_summary"]
