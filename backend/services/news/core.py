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

# 네이버 뉴스 검색 키워드 버킷 (2026 시즌 기준)
NAVER_ESPORTS_QUERIES = [
    "T1 티원",
    "Gen.G 젠지",
    "LCK",
    "LCK CUP LCK컵",
    "롤드컵 Worlds 월즈",
    "VCT Pacific 퍼시픽 킥오프 Kickoff",
    "챌린저스 코리아 CK 2군리그",
]

NAVER_ECONOMY_QUERIES = [
    "코스피 코스닥 주식시장",
    "환율 원달러",
    "한국은행 금통위 기준금리",
    "FOMC 연준 CPI PCE",
    "삼성전자",
    "ETF",
    "반도체 HBM DRAM",
]

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

def calculate_simhash(text: str) -> str:
    """
    텍스트의 Simhash 값을 계산하여 문자열로 반환
    짧은 텍스트의 경우 본문 일부 또는 추가 키를 섞어 안정화하는 것을 권장
    """
    return str(Simhash(text or "").value)

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
