from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .config import TradeEngineConfig

logger = logging.getLogger(__name__)

_DEFAULT_SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "semiconductor": ("반도체", "hbm", "dram", "낸드", "삼성전자", "sk하이닉스"),
    "secondary_battery": ("2차전지", "배터리", "양극재", "리튬", "전해질", "에코프로"),
    "bio_healthcare": ("바이오", "제약", "신약", "임상", "의료기기", "헬스케어"),
    "internet_platform": ("ai", "인공지능", "클라우드", "플랫폼", "인터넷", "데이터센터"),
    "auto_mobility": ("자동차", "전기차", "모빌리티", "자율주행", "현대차", "기아"),
    "finance": ("은행", "증권", "보험", "금융", "금리", "대출", "예대마진"),
    "shipbuilding_defense": ("조선", "방산", "수주", "해운", "선박", "군수"),
    "energy_materials": ("원유", "가스", "전력", "원자력", "태양광", "구리", "철강"),
}

_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "상승",
    "급등",
    "반등",
    "호조",
    "개선",
    "수혜",
    "완화",
    "인하",
    "성장",
    "흑자",
    "확대",
    "증가",
)

_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "하락",
    "급락",
    "부진",
    "악화",
    "긴축",
    "인상",
    "위기",
    "쇼크",
    "적자",
    "축소",
    "감소",
    "우려",
)

_CACHE_SIGNAL: NewsSentimentSignal | None = None
_CACHE_AT: datetime | None = None


@dataclass(slots=True)
class NewsSentimentSignal:
    market_score: float
    sector_scores: dict[str, float]
    sector_keywords: dict[str, tuple[str, ...]]
    article_count: int

    def score_for_name(self, name: str | None) -> tuple[float, bool]:
        normalized = (name or "").strip().lower()
        if not normalized:
            return float(self.market_score), False

        matched_scores: list[float] = []
        for sector, keywords in self.sector_keywords.items():
            if any(k in normalized for k in keywords):
                matched_scores.append(float(self.sector_scores.get(sector, 0.0)))

        if matched_scores:
            return float(sum(matched_scores) / len(matched_scores)), True

        return float(self.market_score), False


def build_news_sentiment_signal(config: TradeEngineConfig) -> NewsSentimentSignal | None:
    if not config.use_news_sentiment:
        return None

    global _CACHE_SIGNAL, _CACHE_AT
    now = datetime.now()
    if (
        _CACHE_SIGNAL is not None
        and _CACHE_AT is not None
        and (now - _CACHE_AT).total_seconds() < max(10, int(config.news_cache_ttl_sec))
    ):
        return _CACHE_SIGNAL

    keywords_by_sector = _load_sector_keywords(config.news_sector_queries_path)
    if not keywords_by_sector:
        return None

    try:
        from backend.core.db import SessionLocal
        from backend.core.models_misc import GameNews
        from backend.core.time_utils import utcnow

        since = utcnow() - timedelta(hours=max(1, int(config.news_lookback_hours)))
        max_rows = max(30, int(config.news_max_articles))

        with SessionLocal() as db:
            rows = (
                db.query(GameNews.title, GameNews.summary, GameNews.full_content)
                .filter(
                    GameNews.source_type == "news",
                    GameNews.published_at >= since,
                )
                .order_by(GameNews.published_at.desc())
                .limit(max_rows)
                .all()
            )
    except Exception:
        logger.warning("failed to build news sentiment signal", exc_info=True)
        return None

    sector_totals: dict[str, float] = {sector: 0.0 for sector in keywords_by_sector}
    sector_hits: dict[str, int] = {sector: 0 for sector in keywords_by_sector}

    for title, summary, full_content in rows:
        text = _compose_text(title, summary, full_content)
        if not text:
            continue
        article_score = _article_sentiment(text)
        if abs(article_score) < 1e-9:
            continue

        for sector, keywords in keywords_by_sector.items():
            if any(k in text for k in keywords):
                sector_totals[sector] += article_score
                sector_hits[sector] += 1

    confidence_divisor = max(2.0, float(max(1, int(config.news_min_articles))) / 2.0)
    sector_scores: dict[str, float] = {}
    for sector, total in sector_totals.items():
        hits = sector_hits.get(sector, 0)
        if hits <= 0:
            sector_scores[sector] = 0.0
            continue
        mean_score = total / float(hits)
        confidence = min(1.0, float(hits) / confidence_divisor)
        sector_scores[sector] = _clamp(mean_score * confidence, -1.0, 1.0)

    active_scores = [sector_scores[s] for s, n in sector_hits.items() if n > 0]
    market_score = float(sum(active_scores) / len(active_scores)) if active_scores else 0.0

    signal = NewsSentimentSignal(
        market_score=_clamp(market_score, -1.0, 1.0),
        sector_scores=sector_scores,
        sector_keywords=keywords_by_sector,
        article_count=len(rows),
    )
    _CACHE_SIGNAL = signal
    _CACHE_AT = now
    return signal


def _load_sector_keywords(path_str: str) -> dict[str, tuple[str, ...]]:
    path = Path(path_str)
    if not path.exists():
        return dict(_DEFAULT_SECTOR_KEYWORDS)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("failed to parse sector keyword config: %s", path, exc_info=True)
        return dict(_DEFAULT_SECTOR_KEYWORDS)

    if isinstance(raw, dict) and isinstance(raw.get("sectors"), dict):
        raw = raw["sectors"]

    if not isinstance(raw, dict):
        return dict(_DEFAULT_SECTOR_KEYWORDS)

    output: dict[str, tuple[str, ...]] = {}
    for sector, keywords in raw.items():
        if not isinstance(sector, str) or not isinstance(keywords, list):
            continue
        normalized = tuple(
            kw.strip().lower()
            for kw in keywords
            if isinstance(kw, str) and kw.strip()
        )
        if normalized:
            output[sector.strip()] = normalized

    if output:
        return output
    return dict(_DEFAULT_SECTOR_KEYWORDS)


def _compose_text(title: str | None, summary: str | None, full_content: str | None) -> str:
    chunks: list[str] = []
    for item in (title, summary, full_content):
        if not item:
            continue
        text = str(item).strip()
        if text:
            chunks.append(text)
    if not chunks:
        return ""
    # full_content까지 모두 쓰면 노이즈가 커져서 길이를 제한.
    return " ".join(chunks).lower()[:1200]


def _article_sentiment(text: str) -> float:
    positive = sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)
    negative = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)
    diff = float(positive - negative)
    if abs(diff) < 1e-9:
        return 0.0
    return _clamp(diff / 3.0, -1.0, 1.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
