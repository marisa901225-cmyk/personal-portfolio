import logging
import os
import json
import random
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
try:
    from sqlalchemy import or_, and_  # type: ignore
    from sqlalchemy.orm import Session  # type: ignore
except Exception:  # pragma: no cover
    Session = object  # type: ignore

    def or_(*args):  # type: ignore
        return ("or_",) + args

    def and_(*args):  # type: ignore
        return ("and_",) + args

try:
    from ...core.models import GameNews  # type: ignore
    from ...core.time_utils import utcnow  # type: ignore
except Exception:  # pragma: no cover
    class _Expr:
        def __init__(self, name: str):
            self.name = name

        def __repr__(self) -> str:
            return self.name

        def __eq__(self, other):  # type: ignore
            return ("==", self.name, other)

        def __ge__(self, other):  # type: ignore
            return (">=", self.name, other)

        def __le__(self, other):  # type: ignore
            return ("<=", self.name, other)

        def in_(self, items):  # type: ignore
            return ("in_", self.name, items)

        def icontains(self, s: str):  # type: ignore
            return ("icontains", self.name, s)

    class _GameNewsDummy:
        source_type = _Expr("GameNews.source_type")
        source_name = _Expr("GameNews.source_name")
        event_time = _Expr("GameNews.event_time")
        league_tag = _Expr("GameNews.league_tag")
        game_tag = _Expr("GameNews.game_tag")
        category_tag = _Expr("GameNews.category_tag")
        title = _Expr("GameNews.title")
        notified_at = _Expr("GameNews.notified_at")  # ✅ 테스트 환경 대비 추가

    GameNews = _GameNewsDummy()  # type: ignore
    from ...core.time_utils import utcnow  # type: ignore
from .catchphrase_selector import choose_phrase
from .catchphrase_constants import (
    build_fallback_lines,
    LOL_CATCHPHRASES,
    VALORANT_CATCHPHRASES,
)

logger = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")
_UTC_TO_KST_OFFSET = timedelta(hours=9)


_KST_LINE_RE = re.compile(r"Start Time\s*\(KST\)\s*:\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})")
_UTC_Z_LINE_RE = re.compile(r"Start Time\s*:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z")
_TEAM_SPLIT_RE = re.compile(r"\s+(?:vs|v)\s+", re.IGNORECASE)


def _ci_contains(col, needle: str):
    """
    SQLAlchemy 기본에는 icontains가 없을 수 있어,
    있으면 icontains, 없으면 ilike로 처리한다.
    """
    if hasattr(col, "icontains"):
        return col.icontains(needle)  # type: ignore
    if hasattr(col, "ilike"):
        return col.ilike(f"%{needle}%")  # type: ignore
    # 테스트/더미 환경 fallback
    return ("icontains_fallback", col, needle)


def _filter_catchphrases(phrases: list[str]) -> list[str]:
    """
    캐치프레이즈 목록을 정제한다. 
    LLM 생성이 아니므로 기본적인 검증(한글 포함 여부 등)만 수행한다.
    """
    out: list[str] = []
    seen = set()
    for phrase in phrases or []:
        p = (phrase or "").strip()
        if not p:
            continue
        if p in seen:
            continue
        seen.add(p)

        # 기본적인 노이즈 필터링 (특수기호 과다 등)
        if re.search(r"[<>\[\]{}\"]", p):
            continue
        if not re.search(r"[가-힣]", p):
            continue
        if len(p) > 100:
            continue

        out.append(p)
    return out


def _parse_kst_from_full_content(full_content: str) -> datetime | None:
    if not full_content:
        return None
    m = _KST_LINE_RE.search(full_content)
    if m:
        try:
            return datetime.fromisoformat(f"{m.group(1)} {m.group(2)}")
        except Exception:
            return None
    m = _UTC_Z_LINE_RE.search(full_content)
    if m:
        try:
            # Z = UTC, convert to KST naive
            dt_utc = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
            return dt_utc.astimezone(KST).replace(tzinfo=None)
        except Exception:
            return None
    return None


def _format_match_time_kst(match) -> str:
    try:
        full_content = getattr(match, "full_content", "") or ""
        parsed = _parse_kst_from_full_content(full_content)
        if parsed:
            return parsed.strftime("%H:%M")
    except Exception:
        pass

    dt = getattr(match, "event_time", None)
    if not dt:
        return "시간 미정"

    try:
        # tz-aware이면 그냥 KST 변환
        if getattr(dt, "tzinfo", None) is not None:
            return dt.astimezone(KST).strftime("%H:%M")

        # ✅ naive면 "UTC로 저장된 값"이라고 확정 -> UTC로 해석 후 KST 변환 (LO 추천 💖)
        dt_utc = dt.replace(tzinfo=timezone.utc)
        return dt_utc.astimezone(KST).strftime("%H:%M")
    except Exception:
        return "시간 미정"


def _extract_teams(match_name: str) -> tuple[str, str]:
    s = (match_name or "").strip()
    if not s:
        return ("팀A", "팀B")

    if "⚔️" in s:
        parts = [p.strip() for p in s.split("⚔️", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return (parts[0], parts[1])

    parts = [p.strip() for p in _TEAM_SPLIT_RE.split(s, 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        return (parts[0], parts[1])

    return ("팀A", "팀B")

def _is_tbd_team_name(name: str) -> bool:
    n = (name or "").strip().casefold()
    return n in {"tbd", "tba"} or "tbd" in n or "tba" in n


def _is_tbd_match_title(match_name: str) -> bool:
    team_a, team_b = _extract_teams(match_name)
    return _is_tbd_team_name(team_a) or _is_tbd_team_name(team_b)




async def check_upcoming_matches(db: Session, catchphrases_file: str, window_minutes: int = 5) -> bool:
    # DB의 event_time은 tzinfo 없이 저장되는 경우가 많아(특히 SQLite),
    # 시스템 로컬타임에 의존하지 않도록 KST를 명시적으로 사용한다.
    # UTC 기준으로 윈도우 계산 (LO의 추천! 💖)
    from datetime import timezone
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    upper_utc = now_utc + timedelta(minutes=window_minutes)
    # 스케줄러 지연이나 이전 실행 실패 시에도 경기 알림을 보낼 수 있도록 하한을 확장
    lower_utc = now_utc - timedelta(minutes=window_minutes)

    # DB 조회 (UTC 기준)
    upcoming = db.query(GameNews).filter(
        GameNews.source_type == "schedule",
        GameNews.source_name == "PandaScore",
        GameNews.notified_at.is_(None),
        and_(GameNews.event_time >= lower_utc, GameNews.event_time <= upper_utc),
        or_(
            GameNews.league_tag.in_(["LCK", "LCK-CL", "LPL", "Worlds", "MSI", "Worlds/MSI", "Asian Games", "EWC"]),
            and_(
                GameNews.game_tag == "Valorant",
                or_(
                    _ci_contains(GameNews.league_tag, "VCT"),
                    _ci_contains(GameNews.league_tag, "Champions"),
                    _ci_contains(GameNews.league_tag, "Masters"),
                    _ci_contains(GameNews.league_tag, "Kickoff"),
                )
            )
        )
    ).all()
    
    # 제외 키워드 목록 (서브 리그 등)
    noise_keywords = [
        "game changers", "gc", "challengers", "division", "open", 
        "premier", "ascension", "trials", "showmatch", "qualifier", "cl"
    ]

    clean_matches = []
    ignored_tbd_matches = []
    for m in upcoming:
        # 서브 리그 필터링 (발로란트 등)
        league_lower = (m.league_tag or "").lower()
        title_lower = (m.title or "").lower()
        
        # LCK CL은 예외적으로 허용할 수도 있지만, 사용자가 "발로란트 메인경기"를 언급했으므로
        # 발로란트인 경우에만 강력하게 필터링하거나, 전체적으로 적용.
        # 일단 LCK CL은 별도 로직으로 수집되므로 여기서는 스케줄 알림에서 제외될 수 있음.
        # 하지만 기존 로직에 LCK-CL이 포함되어 있었음. 
        # 사용자의 요청은 "발로란트 서브경기"가 오는 것을 막는 것.
        
        if m.game_tag == "Valorant":
            is_noise = False
            for kw in noise_keywords:
                # 짧은 키워드(cl 등)는 단어 단위로 매칭하여 오탐 방지
                if len(kw) <= 2:
                    pattern = rf"\b{re.escape(kw)}\b"
                    if re.search(pattern, league_lower) or re.search(pattern, title_lower):
                        is_noise = True
                        break
                elif kw in league_lower or kw in title_lower:
                    is_noise = True
                    break
            if is_noise:
                continue

        title_clean = (m.title or "").replace("[Esports Schedule] ", "")
        if " - " in title_clean:
            _, match_name = title_clean.split(" - ", 1)
        else:
            match_name = title_clean
        if _is_tbd_match_title(match_name):
            # 브라켓이 확정되기 전(TBD vs TBD)에는 알림을 보내지 않되,
            # 추후 동일 윈도우에서 반복 알림이 발생하지 않도록 notified_at만 기록한다.
            m.notified_at = utcnow()
            ignored_tbd_matches.append(m)
            continue
                
        clean_matches.append(m)

    matches_to_notify = clean_matches
    if not matches_to_notify:
        if ignored_tbd_matches:
            db.commit()
            logger.info(f"Ignored {len(ignored_tbd_matches)} TBD matches (not notifying).")
        return False

    # 우선순위 정의 (숫자가 낮을수록 높음)
    priority_map = {
        "Worlds": 1, "MSI": 1, "Worlds/MSI": 1, "Asian Games": 1, "EWC": 1,
        "LCK": 2,
        "LCK-CL": 3,
        "LPL": 4, "VCT": 4, "Champions": 4, "Masters": 4, "Kickoff": 4
    }
    
    def get_priority(m):
        if m.game_tag == "Valorant":
            # 발로란트는 구체적 이름이 태그로 오므로 맵에 없으면 기본 4순위
            return priority_map.get(m.league_tag, 4)
        return priority_map.get(m.league_tag, 99)

    # 우선순위에 따라 정렬
    matches_to_notify.sort(key=get_priority)
    
    # 경기들의 종목 확인
    games_involved = {
        (m.game_tag or "").strip()
        for m in matches_to_notify
        if (m.game_tag or "").strip()
    }

    # 캐치프레이즈 도출 (Constants 중심)
    selected_phrases = []
    
    # 1. catchphrase_constants.py의 상수 리스트 사용 (가장 고퀄리티/안정적)
    for game in games_involved:
        if game == "LoL":
            selected_phrases.extend(LOL_CATCHPHRASES)
        elif game == "Valorant":
            selected_phrases.extend(VALORANT_CATCHPHRASES)

    # 2. JSON 파일 로드 (보조용/동적 업데이트용이나, 현재는 fallbacks가 주력)
    if not selected_phrases:
        if os.path.exists(catchphrases_file):
            try:
                with open(catchphrases_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    if isinstance(saved, list):
                        selected_phrases = saved
                    elif isinstance(saved, dict):
                        for game in games_involved:
                            if game in saved and saved[game]:
                                selected_phrases.extend(saved[game])
            except Exception as e:
                logger.warning(f"Failed to load catchphrases: {e}")
            
    selected_phrases = _filter_catchphrases(selected_phrases)
    if not selected_phrases:
        selected_phrases = [
            "야, 놓치지 마! 🔥", "지금 바로 입장! 🏃‍♂️", "치킨 준비됐나? 🍗", "이번 세트 대박! 🎮"
        ]

    # 상태 파일 경로 (backend/data 폴더로 고정, PathLib 사용)
    current_dir = Path(__file__).resolve().parent
    state_path = current_dir.parent.parent / "data" / "catchphrase_rotation_state.json"
    
    rotation_key = (
        "catchphrases:" + "|".join(sorted(games_involved))
        if games_involved
        else "catchphrases:default"
    )
    selected_phrase = None
    try:
        selected_phrase = choose_phrase(selected_phrases, state_path=state_path, key=rotation_key)
    except Exception:
        selected_phrase = None
    if not selected_phrase:
        selected_phrase = random.choice(selected_phrases)
    lines = [f"🎮 <b>[경기 시작 알림]</b>\n{selected_phrase}\n"]
    for match in matches_to_notify:
        title = match.title.replace("[Esports Schedule] ", "")
        # LoL - DNS vs DK 형태에서 팀명 추출
        if " - " in title:
            _, match_part = title.split(" - ", 1)
            match_name = match_part
        else:
            match_name = title
    
        
        # event_time은 KST 기준으로 저장/표시 (tz-aware이면 KST로 변환)
        event_time_str = _format_match_time_kst(match)
        lines.append(f"🏆 <b>{match.league_tag}</b> | {event_time_str}\n   {match_name}\n")
        
        # 알림 완료 기록 (UTC 통일!)
        match.notified_at = utcnow()
    
    msg = "\n".join(lines)
    try:
        from ...integrations.telegram import send_telegram_message
        await send_telegram_message(msg)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to send match notification: {e}")
        raise
        
    logger.info(f"Sent match notification for {len(matches_to_notify)} matches")
    return True
