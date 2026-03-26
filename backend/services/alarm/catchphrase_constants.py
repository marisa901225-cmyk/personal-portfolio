import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "catchphrases.json"
_CACHE_MTIME: float | None = None
_CACHE_DATA: dict[str, list[str]] | None = None


def _normalize_phrase_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _load_catchphrase_data() -> dict[str, list[str]]:
    global _CACHE_DATA, _CACHE_MTIME

    try:
        mtime = _DATA_PATH.stat().st_mtime
    except FileNotFoundError:
        logger.warning("Catchphrase JSON not found: %s", _DATA_PATH)
        _CACHE_DATA = {"LoL": [], "Valorant": []}
        _CACHE_MTIME = None
        return dict(_CACHE_DATA)

    if _CACHE_DATA is not None and _CACHE_MTIME == mtime:
        return dict(_CACHE_DATA)

    try:
        raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load catchphrase JSON %s: %s", _DATA_PATH, exc)
        raw = {}

    data = {
        "LoL": _normalize_phrase_list(raw.get("LoL")),
        "Valorant": _normalize_phrase_list(raw.get("Valorant")),
    }
    _CACHE_DATA = data
    _CACHE_MTIME = mtime
    return dict(data)


def _phrases_for(game_key: str) -> list[str]:
    return _load_catchphrase_data().get(game_key, [])


LOL_CATCHPHRASES = _phrases_for("LoL")
VALORANT_CATCHPHRASES = _phrases_for("Valorant")


def refresh_catchphrase_constants() -> None:
    global LOL_CATCHPHRASES, VALORANT_CATCHPHRASES
    LOL_CATCHPHRASES = _phrases_for("LoL")
    VALORANT_CATCHPHRASES = _phrases_for("Valorant")


def build_fallback_lines(
    *,
    game_key: str,
    league: str = "",
    team_a: str = "",
    team_b: str = "",
    start_time: str = "",
) -> list[str]:
    """
    고급 알림 구성용 폴백 문구 리스트 반환.
    데이터는 JSON에서 로드하며, 호출 시점 변경도 반영한다.
    """
    refresh_catchphrase_constants()

    templates: list[str] = []
    if game_key == "LoL":
        templates = LOL_CATCHPHRASES
    elif game_key == "Valorant":
        templates = VALORANT_CATCHPHRASES

    if not templates:
        return [f"드디어 {game_key} 승부가 시작됩니다! 🔥"]

    return templates
