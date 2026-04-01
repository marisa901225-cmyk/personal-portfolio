from __future__ import annotations
from typing import Dict, List, Any, Callable, Optional


LOL_INTERNATIONAL_KEYWORDS = (
    "first stand",
    "first-stand",
    "lcq",
    "worlds",
    "world championship",
    "msi",
    "mid-season invitational",
    "esports world cup",
    "ewc",
)

def default_league_tagger(match: dict) -> str:
    """기본 리그 태거: 리그 이름을 반환하거나 종목명을 반환"""
    return (match.get("league") or {}).get("name") or "Unknown"

def valorant_league_tagger(match: dict) -> str:
    """발로란트 특화 리그 태거"""
    serie = (match.get("serie") or {}).get("full_name") or (match.get("serie") or {}).get("name")
    tour = (match.get("tournament") or {}).get("name")
    league = (match.get("league") or {}).get("name")
    return serie or tour or league or "Valorant"

def lol_league_tagger(match: dict) -> str:
    """LoL 특화 리그 태거"""
    league_name = (match.get("league") or {}).get("name") or ""
    lower_league = league_name.lower()
    
    if any(kw in lower_league for kw in LOL_INTERNATIONAL_KEYWORDS):
        return "Worlds/MSI"
    if "lck" in lower_league or "lck cup" in lower_league:
        if any(kw in lower_league for kw in ["challengers", "cl"]):
            return "LCK-CL"
        return "LCK"
    elif "lpl" in lower_league:
        return "LPL"
    elif "lec" in lower_league:
        return "LEC"
    elif "lcs" in lower_league:
        return "LCS"
    return "LoL 기타"

# 리그별 시청 시간대 설정 (KST)
# 형식: {"weekday": 요일(0=월), "start": (시, 분), "end": (시, 분)}
LEAGUE_ACTIVE_WINDOWS: Dict[str, List[Dict[str, Any]]] = {
    # LCK Challengers: 월 14:00, 화 17:00
    "lck-cl": [
        {"weekday": 0, "start": (13, 30), "end": (22, 0)},  # 월요일
        {"weekday": 1, "start": (16, 30), "end": (22, 0)},  # 화요일
    ],
    # LCK: 수목금토일 17:00
    "lck": [
        {"weekday": i, "start": (16, 30), "end": (23, 0)} for i in range(2, 7)  # 수~일
    ],
    # LPL: 평일 15:00 기준 대응 (기사의 길 1경기 시작)
    "lpl": [
        {"weekday": i, "start": (14, 30), "end": (25, 0)} for i in range(7)  # 매일
    ],
    # VCT Pacific: 17:00 KST (주말 중심)
    "vct": [
        {"weekday": i, "start": (16, 30), "end": (23, 0)} for i in range(7)  # 매일
    ],
    # Worlds/MSI: 국제대회 (시즌별로 다름, 보수적으로 14:00~)
    "international": [
        {"weekday": i, "start": (14, 0), "end": (25, 0)} for i in range(7)
    ],
    # LEC: 주로 주말 밤 시간대 (LO의 수면 시각인 22시 이후 알람 억제)
    "lec": [
        {"weekday": i, "start": (22, 0), "end": (22, 0)} for i in range(7)
    ],
}

# 게임 레지스트리 설정
GAME_REGISTRY: Dict[str, Dict[str, Any]] = {
    "league-of-legends": {
        "display_name": "LoL",
        "interest_keywords": ["lck", "lpl", "lec", "worlds", "msi", "월즈", "challengers", "cl"],
        "exclude_keywords": [".a", "academy", "youth", "아카데미", "lcs"],  # Exclude LCS but keep LEC
        "noise_keywords": [],
        "tagger": lol_league_tagger,
        "is_international": lambda tag: tag in ["Worlds/MSI"],
        "enabled": True,
        # 리그별 시간대 매핑
        "league_windows": {
            "LCK-CL": "lck-cl",
            "LCK": "lck",
            "LPL": "lpl",
            "LEC": "lec",
            "Worlds/MSI": "international",
        },
    },
    "valorant": {
        "display_name": "Valorant",
        "interest_keywords": ["vct", "champions", "masters", "kickoff"],
        "exclude_keywords": [],
        "noise_keywords": [
            "game changers", "gc ", "gc-", "monthly", "qualifier", "showmatch", 
            "challengers", "division", "open", "premier", "ascension", "trials"
        ],
        "tagger": valorant_league_tagger,
        "is_international": lambda tag: any(kw in tag.lower() for kw in ["champions", "masters", "kickoff", "ascension"]),
        "enabled": True,
        "league_windows": {
            "default": "vct",  # VCT는 기본 시간대 사용
        },
    },
    "pubg": {
        "display_name": "PUBG",
        "interest_keywords": ["pgs", "pnc", "pgc", "pws"],
        "exclude_keywords": ["open", "qualifier"],
        "noise_keywords": ["daily", "weekly"],
        "tagger": default_league_tagger,
        "is_international": lambda tag: any(kw in tag.lower() for kw in ["pgs", "pnc", "pgc"]),
        "enabled": False,
        "league_windows": {},
    },
}

def get_game_config(game_id: str) -> Optional[Dict[str, Any]]:
    # PandaScore ID 대응 (lol -> league-of-legends 등)
    normalized_id = game_id.lower()
    if normalized_id == "lol":
        normalized_id = "league-of-legends"
    return GAME_REGISTRY.get(normalized_id)


def infer_league_tag_from_name(name: str, videogame: str) -> str:
    """경기 이름에서 리그 태그를 추론합니다."""
    if not name:
        return "default"
    
    name_lower = name.lower()
    
    if videogame == "league-of-legends":
        if any(kw in name_lower for kw in LOL_INTERNATIONAL_KEYWORDS):
            return "Worlds/MSI"
        if "lck" in name_lower or "lck cup" in name_lower:
            if any(kw in name_lower for kw in ["challengers", "cl"]):
                return "LCK-CL"
            return "LCK"
        elif "lpl" in name_lower:
            return "LPL"
        elif "lec" in name_lower:
            return "LEC"
        elif "worlds" in name_lower or "msi" in name_lower:
            return "Worlds/MSI"
        # [NEW] Default to LCK for LoL if no other keywords found
        return "LCK" 
    
    if videogame == "valorant":
        return "vct" # Valorant는 기본적으로 VCT 시간대 사용


def is_league_in_active_window(league_tag: str, game_slug: str, weekday: int, current_time_minutes: int) -> bool:
    """특정 리그가 활성 시간대인지 확인합니다.
    
    Args:
        league_tag: 리그 태그 (예: "LCK", "LCK-CL", "LPL", "default")
        game_slug: 게임 슬러그 (예: "league-of-legends", "valorant")
        weekday: 요일 (0=월요일, 6=일요일)
        current_time_minutes: 현재 시각 (분 단위, 예: 14:30 = 870)
    
    Returns:
        True if in active window, False otherwise
    """
    config = GAME_REGISTRY.get(game_slug, {})
    league_windows = config.get("league_windows", {})
    
    # Find matching window key
    window_key = league_windows.get(league_tag) or league_windows.get("default")
    if not window_key:
        return False  # 🔒 보수적 접근: 윈도우가 정의되지 않은 리그는 차단 (새벽 알림 방지)
    
    windows = LEAGUE_ACTIVE_WINDOWS.get(window_key, [])
    if not windows:
        return False  # 🔒 보수적 접근: 윈도우가 정의되지 않은 리그는 차단 (새벽 알림 방지)
    
    for w in windows:
        w_weekday = w["weekday"] if isinstance(w["weekday"], int) else w["weekday"]
        start_time = w["start"][0] * 60 + w["start"][1]
        end_time = w["end"][0] * 60 + w["end"][1]
        
        # Overnight logic (end > 24:00)
        if end_time > 24 * 60:
            next_weekday = (w_weekday + 1) % 7
            if weekday == w_weekday and current_time_minutes >= start_time:
                return True
            if weekday == next_weekday and current_time_minutes < (end_time - 24 * 60):
                return True
        elif w_weekday == weekday and start_time <= current_time_minutes < end_time:
            return True
    
    return False
