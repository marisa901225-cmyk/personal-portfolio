from __future__ import annotations
from typing import Dict, List, Any, Callable, Optional

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
    
    if "lck" in lower_league:
        if any(kw in lower_league for kw in ["challengers", "cl"]):
            return "LCK-CL"
        return "LCK"
    elif "lpl" in lower_league:
        return "LPL"
    elif "lec" in lower_league:
        return "LEC"
    elif "lcs" in lower_league:
        return "LCS"
    elif any(kw in lower_league for kw in ["worlds", "msi", "mid-season invitational"]):
        return "Worlds/MSI"
    return "LoL 기타"

# 게임 레지스트리 설정
GAME_REGISTRY: Dict[str, Dict[str, Any]] = {
    "league-of-legends": {
        "display_name": "LoL",
        "interest_keywords": ["lck", "lpl", "lec", "lcs", "worlds", "msi", "월즈", "challengers", "cl"],
        "exclude_keywords": [".a", "academy", "youth", "아카데미"],
        "noise_keywords": [],
        "tagger": lol_league_tagger,
        "is_international": lambda tag: tag in ["Worlds/MSI"],
        "enabled": True,  # [NEW] Optimization: Only poll enabled games
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
    },
    "pubg": {
        "display_name": "PUBG",
        "interest_keywords": ["pgs", "pnc", "pgc", "pws"],
        "exclude_keywords": ["open", "qualifier"],
        "noise_keywords": ["daily", "weekly"],
        "tagger": default_league_tagger,
        "is_international": lambda tag: any(kw in tag.lower() for kw in ["pgs", "pnc", "pgc"]),
        "enabled": False,  # PUBG is secondary for now
    },
}

def get_game_config(game_id: str) -> Optional[Dict[str, Any]]:
    # PandaScore ID 대응 (lol -> league-of-legends 등)
    normalized_id = game_id.lower()
    if normalized_id == "lol":
        normalized_id = "league-of-legends"
    return GAME_REGISTRY.get(normalized_id)
