from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field


class TargetIndexAllocation(BaseModel):
    index_group: str = Field(..., description="지수/테마 이름 (예: S&P500)")
    target_weight: float = Field(..., description="상대 비중 (예: 6, 3, 1)")


class DividendRecord(BaseModel):
    year: int
    total: float


class AssetBase(BaseModel):
    name: str
    ticker: Optional[str] = None
    category: str
    currency: Literal["KRW", "USD"] = "KRW"
    amount: float = 0.0
    current_price: float = 0.0
    purchase_price: Optional[float] = None
    realized_profit: float = 0.0
    index_group: Optional[str] = None


class AssetCreate(AssetBase):
    pass


class AssetUpdate(BaseModel):
    name: Optional[str] = None
    ticker: Optional[str] = None
    category: Optional[str] = None
    currency: Optional[Literal["KRW", "USD"]] = None
    amount: Optional[float] = None
    current_price: Optional[float] = None
    purchase_price: Optional[float] = None
    realized_profit: Optional[float] = None
    index_group: Optional[str] = None


class AssetRead(AssetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class TradeBase(BaseModel):
    type: Literal["BUY", "SELL"]
    quantity: float
    price: float
    timestamp: Optional[datetime] = None
    note: Optional[str] = None


class TradeCreate(TradeBase):
    pass


class TradeRead(TradeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    user_id: int
    realized_delta: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_index_allocations: Optional[List[TargetIndexAllocation]] = None
    server_url: Optional[str] = None
    dividend_year: Optional[int] = None
    dividend_total: Optional[float] = None
    dividends: Optional[List[DividendRecord]] = None


class SettingsUpdate(BaseModel):
    target_index_allocations: Optional[List[TargetIndexAllocation]] = None
    server_url: Optional[str] = None
    dividends: Optional[List[DividendRecord]] = None
    dividend_year: Optional[int] = None
    dividend_total: Optional[float] = None


class DistributionItem(BaseModel):
    name: str
    value: float


class PortfolioSummary(BaseModel):
    total_value: float
    total_invested: float
    realized_profit_total: float
    unrealized_profit_total: float
    category_distribution: List[DistributionItem] = []
    index_distribution: List[DistributionItem] = []


class PortfolioResponse(BaseModel):
    assets: List[AssetRead]
    trades: List[TradeRead]
    summary: PortfolioSummary


class PortfolioSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    snapshot_at: datetime
    total_value: float
    total_invested: float
    realized_profit_total: float
    unrealized_profit_total: float
