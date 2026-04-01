import json
import logging
import os
from .catchphrase_fallbacks import build_fallback_lines

logger = logging.getLogger(__name__)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
async def generate_daily_catchphrases() -> bool:
    """
    매일 또는 주기적으로 e스포츠 전용 캐치프레이즈를 생성하여 파일로 저장한다.
    DB에서 다가오는 경기 정보를 가져와 폴백 문구를 구성한다.
    """
    games_to_process = [
        {"key": "LoL", "name": "리그 오브 레전드"},
        {"key": "Valorant", "name": "발로란트"},
    ]

    games_config = []
    for g in games_to_process:
        games_config.append(
            {
                "game_key": g["key"],
                "game_name": g["name"],
            }
        )

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
