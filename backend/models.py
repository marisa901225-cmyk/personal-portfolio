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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    # 발행어음/CMA 세후 이자 자동 계산 설정 (JSON)
    cma_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
        DateTime, default=datetime.utcnow, nullable=False
    )
    realized_delta: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="settings")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
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
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="external_cashflows")
