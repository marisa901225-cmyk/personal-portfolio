import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from simhash import Simhash

# Constants
RSS_FEEDS = {
    "Inven LoL": "https://feeds.feedburner.com/inven/lol",
    "Inven Game Intro": "https://webzine.inven.co.kr/news/rss.php?sclass=12",
    "Inven Game Review": "https://webzine.inven.co.kr/news/rss.php?sclass=11",
    "Inven Ranking Analysis": "https://webzine.inven.co.kr/news/rss.php?sclass=26",
}

STEAMSPY_URL = "https://steamspy.com/api.php"
PANDASCORE_URL = "https://api.pandascore.co"
NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

DEFAULT_NAVER_ESPORTS_QUERIES = [
    "T1 티원",
    "Gen.G 젠지",
    "LCK",
    "LCK CUP LCK컵",
    "롤드컵 Worlds 월즈",
    "VCT Pacific 퍼시픽 킥오프 Kickoff",
    "챌린저스 코리아 CK 2군리그",
]

DEFAULT_NAVER_ECONOMY_QUERIES = [
    "증시 전망 코스피 코스닥",
    "환율 원달러 국채금리",
    "한국은행 금통위 기준금리",
    "FOMC 연준 CPI PCE 물가",
    "반도체 업황 HBM DRAM",
    "2차전지 전기차 배터리",
    "AI 반도체 데이터센터",
    "조선 방산 수주",
    "바이오 제약 임상",
    "원유 가스 전력 원자력",
]

DEFAULT_GOOGLE_NEWS_MACRO_QUERIES = {
    "US": [
        "S&P 500 futures market outlook",
        "Nasdaq futures market outlook",
        "Federal Reserve interest rate outlook",
        "US CPI inflation market reaction",
        "US Treasury yields market outlook",
        "WTI oil prices inflation market",
    ],
    "EU": [
        "ECB rate decision market outlook",
        "Euro Stoxx 50 futures market",
        "German DAX market outlook",
        "FTSE 100 market outlook",
    ],
}

_ECONOMY_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Crypto": (
        "crypto",
        "bitcoin",
        "ethereum",
        "xrp",
        "비트코인",
        "이더리움",
        "가상자산",
        "가상 화폐",
        "코인",
    ),
    "FX/Rates": (
        "환율",
        "환시",
        "원달러",
        "원/달러",
        "원·달러",
        "달러인덱스",
        "forex",
        "fx ",
        "fx/",
        "usdkrw",
    ),
    "Market": (
        "증시",
        "주식시장",
        "코스피",
        "코스닥",
        "선물",
        "수급",
        "s&p 500",
        "s&p",
        "nasdaq",
        "dow",
        "stock market",
        "stocks",
        "futures",
        "ftse",
        "dax",
        "stoxx",
    ),
    "Macro": (
        "연준",
        "fomc",
        "fed",
        "ecb",
        "boj",
        "금통위",
        "기준금리",
        "금리",
        "cpi",
        "pce",
        "inflation",
        "인플레이션",
        "물가",
        "고용",
        "treasury",
        "yield",
        "bond",
        "국채",
        "채권",
        "유가",
        "oil",
    ),
    "Tech/Semicon": (
        "반도체",
        "hbm",
        "dram",
        "낸드",
        "파운드리",
        "semiconductor",
        "chip",
        "nvidia",
        "엔비디아",
        "삼성전자",
        "sk하이닉스",
    ),
    "EV/Auto": (
        "2차전지",
        "전기차",
        "배터리",
        "양극재",
        "리튬",
        "전해질",
        "ev",
        "electric vehicle",
        "자동차",
        "모빌리티",
        "현대차",
        "기아",
    ),
}

_ECONOMY_CATEGORY_ORDER: tuple[str, ...] = (
    "Crypto",
    "FX/Rates",
    "Market",
    "Macro",
    "Tech/Semicon",
    "EV/Auto",
)

_GOOGLE_SOURCE_BLOCKLIST: tuple[str, ...] = (
    "ad hoc news",
    "kalkine media",
    "scanx.trade",
    "stock titan",
    "techstock²",
    "vocal.media",
)


def _dedupe_preserve_order(values: list[str], fallback: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in values or fallback:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output or list(fallback)


def _normalize_google_query_map(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {key: list(value) for key, value in DEFAULT_GOOGLE_NEWS_MACRO_QUERIES.items()}

    output: dict[str, list[str]] = {}
    for region, default_queries in DEFAULT_GOOGLE_NEWS_MACRO_QUERIES.items():
        candidate = raw.get(region)
        if isinstance(candidate, list):
            output[region] = _dedupe_preserve_order(candidate, list(default_queries))
        else:
            output[region] = list(default_queries)
    return output


def load_news_queries() -> tuple[list[str], list[str], dict[str, list[str]]]:
    config_path = Path(__file__).resolve().parents[2] / "data" / "news_queries.json"
    raw: dict[str, object] = {}

    if config_path.exists():
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to load news_queries.json: {e}")

    esports = _dedupe_preserve_order(
        raw.get("esports", []) if isinstance(raw, dict) else [],
        DEFAULT_NAVER_ESPORTS_QUERIES,
    )
    economy = _dedupe_preserve_order(
        raw.get("economy", []) if isinstance(raw, dict) else [],
        DEFAULT_NAVER_ECONOMY_QUERIES,
    )
    google_macro = _normalize_google_query_map(
        raw.get("google_macro", {}) if isinstance(raw, dict) else {}
    )
    return esports, economy, google_macro


def load_naver_queries() -> tuple[list[str], list[str]]:
    esports, economy, _google = load_news_queries()
    return esports, economy


def load_google_macro_queries() -> dict[str, list[str]]:
    _esports, _economy, google = load_news_queries()
    return google


# 검색 키워드 (실행 시 로드)
NAVER_ESPORTS_QUERIES, NAVER_ECONOMY_QUERIES = load_naver_queries()
GOOGLE_NEWS_MACRO_QUERIES = load_google_macro_queries()


def _normalize_topic_text(*parts: str) -> str:
    text = " ".join(str(part or "") for part in parts)
    text = text.lower().replace("&", " and ")
    text = text.replace("·", "").replace("/", "").replace("_", " ")
    text = re.sub(r"[-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _match_keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def determine_news_tags(
    *,
    category: str,
    query: str,
    title: str = "",
    description: str = "",
    gl: str | None = None,
) -> tuple[str, str, bool]:
    """기사 본문/제목 우선으로 game_tag, category_tag, is_international을 추정한다."""
    article_text = _normalize_topic_text(title, description)
    fallback_text = _normalize_topic_text(query)

    if category == "esports":
        game_tag = "Esports"
        category_tag = "General"
        combined = article_text or fallback_text
        if any(kw in combined for kw in ("lol", "롤", "lck", "월즈", "worlds", "msi")):
            return "LoL", "LCK", False
        if any(kw in combined for kw in ("vct", "발로", "퍼시픽", "champions", "masters", "valorant")):
            return "Valorant", "VCT", False
        if any(kw in combined for kw in ("챌린저스", "2군", "ck")):
            return "LoL", "LCK-CL", False
        return game_tag, category_tag, False

    def _pick_category(text: str) -> str | None:
        best_category: str | None = None
        best_score = 0
        for category_name in _ECONOMY_CATEGORY_ORDER:
            score = _match_keyword_score(text, _ECONOMY_CATEGORY_KEYWORDS[category_name])
            if score > best_score:
                best_category = category_name
                best_score = score
        return best_category

    article_category = _pick_category(article_text)
    if article_category:
        category_tag = article_category
    elif article_text:
        category_tag = "General"
    else:
        category_tag = _pick_category(fallback_text) or "General"
    is_international = bool(gl and str(gl).upper() != "KR")
    if not is_international:
        is_international = any(
            keyword in article_text
            for keyword in ("nasdaq", "s&p", "dow", "ftse", "dax", "stoxx", "fomc", "fed", "ecb")
        )
    return "Economy", category_tag, is_international


def is_blocked_google_source(source_name: str | None) -> bool:
    source = (source_name or "").strip().lower()
    return any(blocked in source for blocked in _GOOGLE_SOURCE_BLOCKLIST)

# 출처별 가중치 (안정적인 점수 분포를 위해)
SOURCE_WEIGHT = {
    "Naver": 10,
    "Inven": 8,
    "PandaScore": 6,
    "Google": 7,
    "Steam": 5,
}

logger = logging.getLogger(__name__)

def _normalize_text(text: str) -> str:
    """텍스트 정규화: HTML 태그 제거, 공백 단일화, 소문자 변환, 특수문자 제거."""
    import re
    import html
    # HTML 엔티티 디코딩 및 태그 제거
    text = html.unescape(text or "")
    text = re.sub(r'<[^>]+>', '', text)
    # 소문자 변환 및 특수문자 제거 (한글/영문/숫자 제외)
    text = text.lower()
    text = re.sub(r'[^a-z0-9가-힣\s]', '', text)
    # 모든 공백(개행 포함)을 단일 공백으로 치환
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def calculate_simhash(text: str) -> str:
    """
    강화된 정규화를 거쳐 Simhash 값을 계산.
    짧은 텍스트는 반복을 통해 해시의 안정성을 높임.
    """
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return "0"
    
    # Simhash는 입력이 너무 짧으면 변별력이 떨어질 수 있으므로 보정
    if len(normalized_text) < 20:
        normalized_text = (normalized_text + " ") * 5
        
    return str(Simhash(normalized_text).value)

def get_jaccard_similarity(str1: str, str2: str) -> float:
    """두 문자열 간의 자카드 유사도 계산."""
    s1 = set(_normalize_text(str1).split())
    s2 = set(_normalize_text(str2).split())
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)

def is_duplicate_complex(
    new_title: str, 
    new_hash: str, 
    existing_news_list: list, 
    simhash_threshold: int = 3, 
    jaccard_threshold: float = 0.8
) -> bool:
    """
    Simhash 거리와 자카드 유사도를 결합한 하이브리드 중복 판별.
    existing_news_list는 GameNews 객체들의 리스트여야 함.
    """
    new_h = int(new_hash)
    for old in existing_news_list:
        # 1. Simhash Hamming Distance 검사
        old_h = int(old.content_hash or 0)
        distance = Simhash(new_h).distance(Simhash(old_h))
        if distance <= simhash_threshold:
            return True
        
        # 2. 제목 자카드 유사도 검사 (Simhash가 멀어도 제목이 거의 같으면 중복)
        if get_jaccard_similarity(new_title, old.title) >= jaccard_threshold:
            return True
            
    return False

def calculate_importance_score(
    title: str, 
    source: str, 
    published_at: Optional[datetime] = None,
    category: str = "news"
) -> int:
    """
    뉴스 중요도 점수 계산 (Heuristic)
    
    Args:
        title: 뉴스 제목
        source: 출처 (예: Naver, Inven, PandaScore)
        published_at: 발행 시각 (UTC aware 권장)
        category: 카테고리 (news, schedule, macro 등)
    
    Returns:
        중요도 점수 (높을수록 중요)
    """
    score = 0
    
    # 1. 키워드 가중치 (정규화 후 검색)
    t = (title or "").strip()
    keywords = ["출시", "패치", "대회", "긴급", "연기", "논란", "속보", "오피셜"]
    if any(k in t for k in keywords):
        score += 30
        
    # 2. 출처 가중치 (맵 기반)
    score += SOURCE_WEIGHT.get(source, 0)
        
    # 3. 최신성 (카테고리별 차등 적용)
    if published_at is None:
        return score
    
    # published_at이 naive면 UTC로 간주
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    
    now_utc = datetime.now(timezone.utc)
    delta_hours = (now_utc - published_at).total_seconds() / 3600
    
    # 카테고리별 최신성 기준
    if category == "schedule":
        # e스포츠 일정은 2~6시간이 의미 있음
        if delta_hours < 2:
            score += 25
        elif delta_hours < 6:
            score += 15
    elif category == "macro":
        # 거시경제는 12~24시간도 충분히 의미 있음
        if delta_hours < 12:
            score += 20
        elif delta_hours < 24:
            score += 10
    else:
        # 일반 뉴스는 4시간 기준
        if delta_hours < 4:
            score += 20
        elif delta_hours < 12:
            score += 10
        
    return score
