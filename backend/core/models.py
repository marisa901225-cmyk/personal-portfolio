from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models_misc import (
    GameNews,
    IncomingAlarm,
    SpamRule,
    SpamNews,
    SpamAlarm,
    SchedulerState,
    EconRateState,
    KrOptionBoardSnapshot,
    EsportsMatch,
)
from .time_utils import utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    assets: Mapped[List["Asset"]] = relationship(
        "Asset", back_populates="user", cascade="all, delete-orphan"
    )
    trades: Mapped[List["Trade"]] = relationship(
        "Trade", back_populates="user", cascade="all, delete-orphan"
    )
    fx_transactions: Mapped[List["FxTransaction"]] = relationship(
        "FxTransaction", back_populates="user", cascade="all, delete-orphan"
    )
    settings: Mapped[List["Setting"]] = relationship(
        "Setting", back_populates="user", cascade="all, delete-orphan"
    )
    snapshots: Mapped[List["PortfolioSnapshot"]] = relationship(
        "PortfolioSnapshot", back_populates="user", cascade="all, delete-orphan"
    )
    yearly_cashflows: Mapped[List["YearlyCashflow"]] = relationship(
        "YearlyCashflow", back_populates="user", cascade="all, delete-orphan"
    )
    external_cashflows: Mapped[List["ExternalCashflow"]] = relationship(
        "ExternalCashflow", back_populates="user", cascade="all, delete-orphan"
    )
    expenses: Mapped[List["Expense"]] = relationship(
        "Expense", back_populates="user", cascade="all, delete-orphan"
    )
    merchant_patterns: Mapped[List["MerchantPattern"]] = relationship(
        "MerchantPattern", back_populates="user", cascade="all, delete-orphan"
    )
    ai_reports: Mapped[List["AiReport"]] = relationship(
        "AiReport", back_populates="user", cascade="all, delete-orphan"
    )
    memories: Mapped[List["UserMemory"]] = relationship(
        "UserMemory", back_populates="user", cascade="all, delete-orphan"
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ticker: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="KRW")

    amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    purchase_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_profit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    index_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    market_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # KRX, NASDAQ, NYSE 등
    # 발행어음/CMA 세후 이자 자동 계산 설정 (JSON)
    cma_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    tags: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 'past' | 'present' etc

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User", back_populates="assets")
    trades: Mapped[List["Trade"]] = relationship(
        "Trade", back_populates="asset", cascade="all, delete-orphan"
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), nullable=False)

    type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'BUY' | 'SELL'
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    realized_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="trades")
    asset: Mapped[Asset] = relationship("Asset", back_populates="trades")


class FxTransaction(Base):
    __tablename__ = "fx_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'BUY' | 'SELL' | 'SETTLEMENT'
    currency: Mapped[str] = mapped_column(String(10), nullable=False)  # 'KRW' | 'USD'
    fx_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    krw_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="fx_transactions")


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    target_index_allocations: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    server_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dividend_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dividend_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    dividends: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    usd_fx_base: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    usd_fx_now: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    benchmark_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    benchmark_return: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    benchmark_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    kis_app: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    kis_sec: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    kis_acct_stock: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kis_prod: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    kis_htsid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kis_prod_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kis_ops_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kis_vps_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kis_vops_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kis_agent: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    kis_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kis_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    # KIS 토큰 갱신 분산 락 (스탬피드 방지)
    token_refresh_locked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    # KIS 서킷브레이커 상태
    kis_auth_failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kis_circuit_open_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="settings")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    total_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_invested: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    realized_profit_total: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    unrealized_profit_total: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="snapshots")


class YearlyCashflow(Base):
    """연도별 입출금 내역 (원금 흐름 추적용)"""
    __tablename__ = "yearly_cashflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    deposit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    withdrawal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="yearly_cashflows")

class ExternalCashflow(Base):
    """XIRR 계산을 위한 개별 입출금 내역 (순수 외부 유입/유출)"""
    __tablename__ = "external_cashflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)  # 입금(+), 출금(-)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    account_info: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="external_cashflows")


class Expense(Base):
    """소비 데이터 추적 (소비 엔진용)"""
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    date: Mapped[date] = mapped_column(Date, nullable=False)  # 결제일
    amount: Mapped[float] = mapped_column(Float, nullable=False)  # 금액 (음수: 지출, 양수: 환불/수입)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # 식비, 교통, 쇼핑, 고정지출 등
    merchant: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # 가맹점명 (스타벅스 강남점, 쿠팡 등)
    method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 결제수단 (현대카드, 토스뱅크 등)
    is_fixed: Mapped[bool] = mapped_column(Integer, nullable=False, default=False)  # 고정지출 여부
    memo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # AI가 남기는 비고

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship("User", back_populates="expenses")


class MerchantPattern(Base):
    """학습된 가맹점 분류 패턴 (사용자 수동 수정 및 자동 학습 결과)"""
    __tablename__ = "merchant_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    merchant: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="merchant_patterns")


class AiReport(Base):
    """AI 생성 리포트 저장"""
    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    period_quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    period_half: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    query: Mapped[str] = mapped_column(String(500), nullable=False)  # 요청 문장
    report: Mapped[str] = mapped_column(Text, nullable=False)  # 생성된 리포트 텍스트
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # 사용된 AI 모델
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # AI 생성 시각

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="ai_reports")


class UserMemory(Base):
    """사용자가 기억해달라고 요청한 정보 (장기 기억)"""
    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general", nullable=False) # profile, preference, project, fact, general
    key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # 중복 시 최신본 유지를 위한 키워드
    importance: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True) # TTL용
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="memories")
