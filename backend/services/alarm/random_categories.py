# backend/services/alarm/random_categories.py
"""랜덤 메시지 생성을 위한 카테고리 키워드 및 상태 관리 (JSON 기반 핫 리로드)"""
import json
import os
import random
import re
from datetime import datetime
from typing import List, Optional, Dict
import logging

logger = logging.getLogger(__name__)

# 경로 설정 (도커 및 로컬 환경 호환)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.path.join(_BASE_DIR, "data")

CONFIG_FILE = os.path.join(_DATA_DIR, "random_topic_config.json")
_RECENT_CATEGORY_FILE = os.path.join(_DATA_DIR, "recent_categories.json")
_RANDOM_TOPIC_STATE_FILE = os.path.join(_DATA_DIR, "random_topic_state.json")

# 핫 리로드를 위한 캐시
_config_cache: Optional[Dict] = None
_config_mtime: Optional[float] = None
_recent_categories: List[str] = []
_RECENT_CATEGORY_MAX = 3


def _load_config() -> Dict:
    """JSON 설정 파일 로드 (파일 변경 시 자동 리로드)"""
    global _config_cache, _config_mtime
    
    try:
        current_mtime = os.path.getmtime(CONFIG_FILE)
        
        # 캐시가 있고 파일이 변경되지 않았으면 캐시 반환
        if _config_cache is not None and _config_mtime == current_mtime:
            return _config_cache
        
        # 파일 로드
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        _config_cache = config
        _config_mtime = current_mtime
        
        logger.info(f"🔄 Random topic config loaded/reloaded from {CONFIG_FILE}")
        return config
    
    except FileNotFoundError:
        logger.error(f"❌ Config file not found: {CONFIG_FILE}")
        return _get_fallback_config()
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid JSON in config file: {e}")
        return _get_fallback_config()
    except Exception as e:
        logger.error(f"❌ Failed to load config: {e}")
        return _get_fallback_config()


def _get_fallback_config() -> Dict:
    """설정 파일 로드 실패 시 기본값 반환"""
    return {
        "space_keywords": ["우주", "천문", "행성"],
        "formats": ["질문형으로 시작해라", "팩트 단언형으로 시작해라"],
        "categories": {
            "우주/천문학": ["우주", "천문", "행성"],
            "기술/엔지니어링": ["기술", "로봇", "AI"],
        }
    }


# 동적 속성: JSON에서 로드
@property
def FORMATS() -> List[str]:
    """랜덤 메시지 시작 형식"""
    return _load_config().get("formats", [])


@property
def CATEGORY_KEYWORDS() -> Dict[str, List[str]]:
    """카테고리별 핵심 키워드 맵"""
    return _load_config().get("categories", {})


@property
def ALL_CATEGORIES() -> List[str]:
    """모든 카테고리 목록"""
    return list(_load_config().get("categories", {}).keys())


# 함수형 접근
def get_formats() -> List[str]:
    """랜덤 메시지 시작 형식 반환"""
    return _load_config().get("formats", [])


def get_category_keywords() -> Dict[str, List[str]]:
    """카테고리별 키워드 맵 반환"""
    return _load_config().get("categories", {})


def get_all_categories() -> List[str]:
    """모든 카테고리 목록 반환"""
    return list(_load_config().get("categories", {}).keys())


def get_voices() -> Dict[str, str]:
    """캐릭터 목소리 맵 반환 (이름: 규칙)"""
    return _load_config().get("voices", {})


def load_recent_categories() -> List[str]:
    """영구 저장된 최근 카테고리 목록 로드 (파일에서 항상 최신 상태 로드)"""
    global _recent_categories
    try:
        if os.path.exists(_RECENT_CATEGORY_FILE):
            with open(_RECENT_CATEGORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    _recent_categories = data
    except Exception as e:
        logger.warning(f"⚠️ Failed to load recent categories: {e}")
    return list(_recent_categories)


def save_recent_category(category: str) -> None:
    """카테고리를 최근 목록에 추가하고 파일에 저장"""
    global _recent_categories
    load_recent_categories()
    if category in _recent_categories:
        _recent_categories.remove(category)
    _recent_categories.insert(0, category)
    _recent_categories = _recent_categories[:_RECENT_CATEGORY_MAX]
    try:
        os.makedirs(os.path.dirname(_RECENT_CATEGORY_FILE), exist_ok=True)
        with open(_RECENT_CATEGORY_FILE, "w", encoding="utf-8") as f:
            json.dump(_recent_categories, f, ensure_ascii=False)
        logger.info(f"📍 Recent categories saved: {_recent_categories}")
    except Exception as e:
        logger.error(f"❌ Failed to save recent categories: {e}", exc_info=True)


def load_last_random_topic_sent_at() -> Optional[datetime]:
    """마지막 랜덤 메시지 발송 시각 로드"""
    try:
        if not os.path.exists(_RANDOM_TOPIC_STATE_FILE):
            return None
        with open(_RANDOM_TOPIC_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        val = (data or {}).get("last_sent_at")
        if not val:
            return None
        return datetime.fromisoformat(val)
    except Exception as e:
        logger.warning(f"⚠️ Failed to load last random topic state: {e}")
        return None


def save_last_random_topic_sent_at(sent_at: datetime) -> None:
    """마지막 랜덤 메시지 발송 시각 저장"""
    try:
        os.makedirs(os.path.dirname(_RANDOM_TOPIC_STATE_FILE), exist_ok=True)
        with open(_RANDOM_TOPIC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_sent_at": sent_at.isoformat(timespec="seconds")}, f, ensure_ascii=False)
        logger.info(f"🕒 Last random topic state updated: {sent_at.isoformat(timespec='seconds')}")
    except Exception as e:
        logger.error(f"❌ Failed to save last random topic state: {e}", exc_info=True)


def pick_keywords_for_constraints(category: str, *, count: int = 4) -> List[str]:
    """카테고리에서 랜덤으로 N개의 키워드를 선택 (한국어 우선)"""
    category_keywords = get_category_keywords()
    keywords = list(category_keywords.get(category) or [])
    if not keywords:
        # ✅ 키워드 리스트가 비어있으면 빈 리스트 반환 (LO 요청: 카테고리 자율성 확보)
        return []
    korean_keywords = [k for k in keywords if re.search(r"[가-힣]", k)]
    pool = korean_keywords or keywords
    if len(pool) <= count:
        return pool
    return random.sample(pool, k=count)


def has_category_anchor(text: str, category: str) -> bool:
    """카테고리별 핵심 키워드가 최소 1개 포함되는지 검사"""
    if not text:
        return False
    category_keywords = get_category_keywords()
    keywords = category_keywords.get(category)
    if not keywords:
        # ✅ 키워드가 정의되지 않은 카테고리는 검증 생략 (항상 통과)
        return True
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)

