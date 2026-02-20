from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, Index, Float
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .time_utils import utcnow


class IncomingAlarm(Base):
    """Tasker에서 수신된 Raw 알림 (Batch 처리 대기열)"""
    __tablename__ = "incoming_alarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    masked_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sender: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # New rich fields
    app_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    package: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    app_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    conversation: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # pending, processed, discarded
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # rule, nb, llm
    classification: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SpamAlarm(Base):
    """필터링되어 버려진 알림 데이터 (필터링 규칙 정교화용)"""
    __tablename__ = "spam_alarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    masked_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sender: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Rich fields
    app_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    package: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    app_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    conversation: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # 필터링 타입 (placeholder, ignored, spam, promo 등)
    classification: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # 구체적인 사유 (매칭된 키워드 등)
    discard_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # 운영 고도화용 컬럼 추가
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    is_restored: Mapped[bool] = mapped_column(Integer, default=False)
    restored_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    restored_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SpamRule(Base):
    """동적 스팸 필터링 규칙"""
    __tablename__ = "spam_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # 'contains' | 'regex' | 'promo_combo'
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    # 'political' | 'stock' | 'promo' | 'general'
    category: Mapped[str] = mapped_column(String(50), default="general")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Integer, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class GameNews(Base):
    """게임 뉴스 및 일정 데이터 (RAG 지식 베이스)"""
    __tablename__ = "game_news"
    __table_args__ = (
        Index("idx_game_news_src_notified_time", "source_type", "source_name", "notified_at", "event_time"),
        Index("idx_game_news_news_game_published", "source_type", "game_tag", "published_at"),
        Index("idx_game_news_title", "title"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # 중복 방지 (SimHash)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Metadata for Hybrid Search
    game_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # LoL, Valorant
    team_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # T1, GenG
    league_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # LCK, LPL, Worlds
    category_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Macro, Tech, Stock, FX 등
    is_international: Mapped[bool] = mapped_column(Integer, default=False)
    event_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)  # 경기 일정 등

    source_type: Mapped[str] = mapped_column(String(20), default="news")  # news, schedule, patch
    source_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Inven, Steam

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    full_content: Mapped[Text] = mapped_column(Text, nullable=False)
    chunk_content: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)
    
    # 영문 뉴스의 경우 LLM으로 생성한 한국어 요약 (원문은 full_content에 유지)
    summary: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)

    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True) # 알림 전송 시각 기록 (LO 추천 💖)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class SpamNews(Base):
    """광고성/스팸으로 분류된 뉴스 데이터 (필터링 로직 고도화용)"""
    __tablename__ = "spam_news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # 중복 방지 (SimHash)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Metadata
    game_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category_tag: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_international: Mapped[bool] = mapped_column(Integer, default=False)
    event_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    source_type: Mapped[str] = mapped_column(String(20), default="news") # news, schedule
    source_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    full_content: Mapped[Text] = mapped_column(Text, nullable=False)
    summary: Mapped[Optional[Text]] = mapped_column(Text, nullable=True)

    published_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    
    # 왜 스팸으로 분류되었는지 기록 (패턴 매칭 결과 등)
    spam_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # 운영 고도화용 컬럼 추가
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    is_restored: Mapped[bool] = mapped_column(Integer, default=False)
    restored_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    restored_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

class SchedulerState(Base):
    """스케줄러 작업 실행 상태 및 이력 기록"""

    __tablename__ = "scheduler_states"

    job_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(
        String(20), default="idle"
    )  # idle, running, success, failure

    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_failure_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class EconRateState(Base):
    """경제 지표(기준금리) 변경 감지 상태 저장"""
    __tablename__ = "econ_rate_states"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)

    fed_funds_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fed_funds_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    bok_base_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bok_base_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class KrOptionBoardSnapshot(Base):
    """국내 옵션 전광판 일별 스냅샷 (주간 파생 심리 브리핑용)"""

    __tablename__ = "kr_option_board_snapshots"
    __table_args__ = (
        Index("idx_kr_option_board_snapshots_trading_date", "trading_date", unique=True),
        Index("idx_kr_option_board_snapshots_collected_at", "collected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    trading_date: Mapped[str] = mapped_column(String(8), nullable=False)
    maturity_month: Mapped[str] = mapped_column(String(6), nullable=False)
    market_cls: Mapped[str] = mapped_column(String(6), nullable=False, default="")

    call_bid_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_ask_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    put_bid_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    put_ask_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    call_oi_change_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    put_oi_change_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bid_pressure: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    oi_pressure: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    put_call_bid_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


class EsportsMatch(Base):
    """E-Sports 매치 상태 캐시 (스마트 폴링 로직용)"""
    __tablename__ = "esports_matches"

    match_id: Mapped[int] = mapped_column(Integer, primary_key=True)  # PandaScore match ID

    # Match context
    league_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    serie_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    tournament_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    videogame: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # lol, valorant, pubg
    name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    # Match Status (from PandaScore: not_started, running, finished, canceled, postponed)
    status: Mapped[str] = mapped_column(String(20), default="not_started", nullable=False, index=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    begin_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    end_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Smart Polling 상태
    last_seen_running_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    missing_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 알림 멱등성 (중복 방지)
    start_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    imminent_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 다음 경기 연결 (선택적)
    next_match_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
