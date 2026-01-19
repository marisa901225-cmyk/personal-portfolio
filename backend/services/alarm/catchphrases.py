import json
import logging
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from ...core.db import SessionLocal
from ...core.models import GameNews
from .catchphrase_fallbacks import build_fallback_lines

logger = logging.getLogger(__name__)

_KST_LINE_RE = re.compile(r"Start Time\s*\(KST\)\s*:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
_UTC_Z_LINE_RE = re.compile(r"Start Time\s*:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")


def _ci_contains(col, needle: str):
    # SQLAlchemy 기본에는 icontains가 없을 수 있어, 있으면 icontains, 없으면 ilike 사용
    if hasattr(col, "icontains"):
        return col.icontains(needle)  # type: ignore
    return col.ilike(f"%{needle}%")  # type: ignore


def _fallback_lines(cfg: dict) -> list[str]:
    return build_fallback_lines(
        game_key=cfg["game_key"],
        league=cfg["league"],
        team_a=cfg["team_a"],
        team_b=cfg["team_b"],
        start_time=cfg["start_time"],
    )


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _get_match_time_kst_str(match, kst: ZoneInfo) -> str:
    # 1) full_content의 KST 텍스트 우선
    try:
        full_content = getattr(match, "full_content", "") or ""
        m = _KST_LINE_RE.search(full_content)
        if m:
            dt = datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
            return dt.strftime("%H:%M")
    except Exception:
        pass

    # 2) full_content의 UTC(Z) 텍스트를 KST로 변환
    try:
        full_content = getattr(match, "full_content", "") or ""
        m = _UTC_Z_LINE_RE.search(full_content)
        if m:
            dt_utc = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(kst).strftime("%H:%M")
    except Exception:
        pass

    # 3) event_time 기반 (DB는 UTC naive라고 가정 → UTC로 해석 후 KST 변환)
    try:
        dt = getattr(match, "event_time", None)
        if not dt:
            return "시간 미정"

        if getattr(dt, "tzinfo", None) is not None:
            return dt.astimezone(kst).strftime("%H:%M")

        # ✅ naive면 UTC로 저장된 값으로 해석
        dt_utc = dt.replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(kst).strftime("%H:%M")
    except Exception:
        return "시간 미정"


def _extract_teams_from_title(title: str) -> tuple[str, str]:
    # "[Esports Schedule] LoL - A vs B" / "LoL - A vs B" / "A vs B" 등을 최대한 안정적으로 파싱
    s = (title or "").replace("[Esports Schedule] ", "").strip()

    if " - " in s:
        s = s.split(" - ", 1)[1].strip()

    # vs/v 주변 공백 기준 (팀명에 v가 포함되는 케이스 방지)
    m = re.split(r"\s+(?:vs|v)\s+", s, maxsplit=1, flags=re.IGNORECASE)
    if len(m) == 2 and m[0].strip() and m[1].strip():
        return (m[0].strip(), m[1].strip())

    return ("팀A", "팀B")


async def generate_daily_catchphrases() -> bool:
    """
    매일 또는 주기적으로 e스포츠 전용 캐치프레이즈를 생성하여 파일로 저장한다.
    DB에서 다가오는 경기 정보를 가져와 폴백 문구를 구성한다.
    """
    KST = ZoneInfo("Asia/Seoul")

    db = SessionLocal()

    # ✅ DB는 PandaScore UTC 기준(naive)로 저장된다고 가정 → 비교는 UTC로 통일
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    games_to_process = [
        {"key": "LoL", "name": "리그 오브 레전드"},
        {"key": "Valorant", "name": "발로란트"},
    ]

    games_config = []

    try:
        for g in games_to_process:
            games_config.append(
                {
                    "game_key": g["key"],
                    "game_name": g["name"],
                }
            )
    finally:
        db.close()

    results = {"LoL": [], "Valorant": []}

    for cfg in games_config:
        # 유료 LLM 호출 없음: 폴백만 사용
        lines = build_fallback_lines(game_key=cfg["game_key"])
        results[cfg["game_key"]] = _dedupe_preserve_order(lines)[:20]

    save_path = os.getenv(
        "CATCHPHRASE_SAVE_PATH",
        os.path.join(os.path.dirname(__file__), "../../data/esports_catchphrases_v2.json")
    )
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info("Daily catchphrases generated and saved to %s", save_path)
        return True
    except Exception as e:
        logger.error("Failed to save generated catchphrases: %s", e)
        return False
