import logging
import os
import json
import random
import re
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
from .catchphrase_selector import choose_phrase
from .catchphrase_fallbacks import build_fallback_lines
from .sanitizer import clean_exaone_tokens

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
    out: list[str] = []
    seen = set()
    for phrase in phrases or []:
        p = clean_exaone_tokens((phrase or "").strip())
        if not p:
            continue
        if p in seen:
            continue
        seen.add(p)

        if re.search(r"[<>\[\]{}\"]", p):
            continue
        if not re.search(r"[가-힣]", p):
            continue
        if len(p) > 80:
            continue

        # LLM 서두 문구/설명 배제
        if any(bad in p for bad in ["요구사항을 정리", "정확히 10줄", "출력은 ", "Think", "사고과정"]):
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


def _fallback_phrases_for_matches(matches) -> list[str]:
    # 경기 알림 단계의 폴백은 "짧은 기본 문구"가 아니라,
    # 미리 준비한 고퀄 폴백 문구를 사용한다.
    phrases: list[str] = []
    seen_game_keys = set()
    for m in matches or []:
        game_key = getattr(m, "game_tag", None) or ""
        if game_key in seen_game_keys:
            continue
        if game_key not in ("LoL", "Valorant"):
            continue
        seen_game_keys.add(game_key)
        match_name = ""
        try:
            title = (getattr(m, "title", "") or "").replace("[Esports Schedule] ", "")
            if " - " in title:
                _, match_name = title.split(" - ", 1)
            else:
                match_name = title
        except Exception:
            match_name = ""

        team_a, team_b = _extract_teams(match_name)
        league = getattr(m, "league_tag", None) or (game_key + " 리그")
        start_time = _format_match_time_kst(m)
        phrases.extend(
            build_fallback_lines(
                game_key=game_key,
                league=league,
                team_a=team_a,
                team_b=team_b,
                start_time=start_time,
            )
        )
    return _filter_catchphrases(phrases)


async def check_upcoming_matches(db: Session, catchphrases_file: str, window_minutes: int = 5) -> bool:
    # DB의 event_time은 tzinfo 없이 저장되는 경우가 많아(특히 SQLite),
    # 시스템 로컬타임에 의존하지 않도록 KST를 명시적으로 사용한다.
    # UTC 기준으로 윈도우 계산 (LO의 추천! 💖)
    from datetime import timezone
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    upper_utc = now_utc + timedelta(minutes=window_minutes)
    # 아래쪽 범위는 경기 시작 직전~직후를 잡기 위해 약간의 여유(5분)를 둔다.
    lower_utc = now_utc - timedelta(minutes=window_minutes) if window_minutes > 5 else now_utc

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
                
        clean_matches.append(m)

    matches_to_notify = clean_matches
    if not matches_to_notify: return False

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
    
    # 캐치프레이즈 도출 (V2 우선, 없으면 레거시)
    default_phrase = "야, 놓치지 마! 🔥"
    default_list = [default_phrase, "지금 바로 입장! 🏃‍♂️", "치킨 준비됐나? 🍗", "이번 세트 대박! 🎮"]
    
    # catchphrases_file이 이미 *_v2.json일 수 있어, v2_v2.json로 꼬이지 않도록 정규화
    is_v2_path = catchphrases_file.endswith("_v2.json")
    catchphrases_v2_file = catchphrases_file if is_v2_path else catchphrases_file.replace(".json", "_v2.json")
    catchphrases_v1_file = catchphrases_file.replace("_v2.json", ".json") if is_v2_path else catchphrases_file
    selected_phrases = []
    
    # 경기들의 종목 확인 (None 방어 로직 추가)
    games_involved = {
        (m.game_tag or "").strip()
        for m in matches_to_notify
        if (m.game_tag or "").strip()
    }
    
    if os.path.exists(catchphrases_v2_file):
        try:
            with open(catchphrases_v2_file, 'r', encoding='utf-8') as f:
                saved_v2 = json.load(f)
                # 혼합 경기의 경우 섞어서 선택하거나 혹은 주력 종목 선택
                for game in games_involved:
                    if game in saved_v2 and saved_v2[game]:
                        selected_phrases.extend(saved_v2[game])
        except Exception as e:
            logger.warning(f"Failed to load catchphrases_v2: {e}")
            
    if not selected_phrases and os.path.exists(catchphrases_v1_file):
        try:
            with open(catchphrases_v1_file, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                if saved and isinstance(saved, list): selected_phrases = saved
        except Exception as e:
            logger.warning(f"Failed to load catchphrases: {e}")
            
    selected_phrases = _filter_catchphrases(selected_phrases)
    if not selected_phrases:
        selected_phrases = _fallback_phrases_for_matches(matches_to_notify) or default_list

    state_path = os.path.join(os.path.dirname(__file__), "../../data/catchphrase_rotation_state.json")
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
        match.notified_at = datetime.utcnow()
    
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
