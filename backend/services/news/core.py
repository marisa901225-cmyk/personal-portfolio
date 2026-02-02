import logging
import os
from datetime import datetime, timezone
from typing import Optional
from simhash import Simhash

# Constants
RSS_FEEDS = {
    "inven_lol": "https://feeds.feedburner.com/inven/lol",
}

STEAMSPY_URL = "https://steamspy.com/api.php"
PANDASCORE_URL = "https://api.pandascore.co"
NAVER_NEWS_URL = "https://openapi.naver.com/v1/search/news.json"

# 네이버 뉴스 검색 키워드 로딩
def load_naver_queries():
    import json
    from pathlib import Path
    
    # 기본값
    default_esports = [
        "T1 티원",
        "Gen.G 젠지",
        "LCK",
        "LCK CUP LCK컵",
        "롤드컵 Worlds 월즈",
        "VCT Pacific 퍼시픽 킥오프 Kickoff",
        "챌린저스 코리아 CK 2군리그",
    ]
    default_economy = [
        "코스피 코스닥 주식시장",
        "환율 원달러",
        "한국은행 금통위 기준금리",
        "FOMC 연준 CPI PCE",
        "삼성전자",
        "ETF",
        "반도체 HBM DRAM",
    ]
    
    config_path = Path(__file__).resolve().parents[2] / "data" / "news_queries.json"
    
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("esports", default_esports), data.get("economy", default_economy)
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to load news_queries.json: {e}")
            
    return default_esports, default_economy

# 검색 키워드 (실행 시 로드)
NAVER_ESPORTS_QUERIES, NAVER_ECONOMY_QUERIES = load_naver_queries()

# 해외 거시경제 키워드 (구글 뉴스 RSS용)
GOOGLE_NEWS_MACRO_QUERIES = {
    "US": [
        "S&P 500 stock market",
        "Nasdaq composite index",
        "FOMC Fed interest rate",
        "US CPI inflation",
        "Treasury yields bonds",
        "ETF market trends",
    ],
    "EU": [
        "ECB interest rate decision",
        "Euro Stoxx 50 index",
        "German DAX stock",
        "UK FTSE 100",
    ],
}

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
