from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


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

    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GameNews(Base):
    """게임 뉴스 및 일정 데이터 (RAG 지식 베이스)"""
    __tablename__ = "game_news"

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

    published_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
