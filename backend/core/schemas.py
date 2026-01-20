from __future__ import annotations

from datetime import datetime, date
from typing import List, Optional, Literal

from pydantic import BaseModel, ConfigDict, Field


class TargetIndexAllocation(BaseModel):
    index_group: str = Field(..., description="지수/테마 이름 (예: S&P500)")
    target_weight: float = Field(..., description="상대 비중 (예: 6, 3, 1)")


class DividendRecord(BaseModel):
    year: int
    total: float


class CmaConfig(BaseModel):
    principal: float = Field(..., ge=0, description="기초 원금")
    annual_rate: float = Field(..., ge=0, le=1.0, description="연수익률 (예: 0.035)")
    tax_rate: float = Field(..., ge=0, le=1.0, description="이자소득세율 (예: 0.154)")
    start_date: str = Field(..., description="수익 산정 시작일 (YYYY-MM-DD)")

    @field_validator("annual_rate", "tax_rate")
    @classmethod
    def validate_rates(cls, v: float) -> float:
        if v > 1.0:
            # 도라의 걱정 해결! 15.4 같은 입력을 0.154로 자동 보정하거나 에러 발생
            # 여기서는 엄격하게 에러를 발생시켜 폭발을 방지합니다. 💖
            raise ValueError("Rate must be between 0 and 1 (e.g., 0.154 for 15.4%)")
        return v


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
    cma_config: Optional[CmaConfig] = None
    tags: Optional[str] = None


class AssetCreate(AssetBase):
    pass


class AssetUpdate(AssetBase):
    """
    Asset 정보 수정 스키마.
    AssetBase를 상속받되, 모든 필드를 Optional로 처리하여 중복을 제거합니다. (지옥 같은 관리 탈출! 💖)
    """
    name: Optional[str] = None
    ticker: Optional[str] = None
    category: Optional[str] = None
    currency: Optional[Literal["KRW", "USD"]] = None
    amount: Optional[float] = None
    current_price: Optional[float] = None
    # 상속받은 필드들을 명시적으로 Optional 선언하여 부분 업데이트 지원
    purchase_price: Optional[float] = None
    realized_profit: Optional[float] = None
    index_group: Optional[str] = None
    cma_config: Optional[CmaConfig] = None
    tags: Optional[str] = None


class AssetCalibration(BaseModel):
    actual_amount: float
    actual_avg_price: float


class AssetRead(AssetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class TradeBase(BaseModel):
    type: Literal["BUY", "SELL", "DIVIDEND"]
    quantity: float = 0.0
    price: float = 0.0
    timestamp: Optional[datetime] = None
    note: Optional[str] = None


class TradeCreate(TradeBase):
    asset_id: int


class TradeUpdate(BaseModel):
    type: Optional[Literal["BUY", "SELL", "DIVIDEND"]] = None
    quantity: Optional[float] = None
    price: Optional[float] = None
    timestamp: Optional[datetime] = None
    note: Optional[str] = None


class TradeRead(TradeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    asset_id: int
    asset_name: Optional[str] = None
    asset_ticker: Optional[str] = None
    user_id: int
    realized_delta: Optional[float] = None
    created_at: datetime
    updated_at: datetime


class FxTransactionBase(BaseModel):
    trade_date: date
    type: Literal["BUY", "SELL", "SETTLEMENT"]
    currency: Literal["KRW", "USD"]
    fx_amount: Optional[float] = None
    krw_amount: Optional[float] = None
    rate: Optional[float] = None
    description: Optional[str] = None
    note: Optional[str] = None


class FxTransactionCreate(FxTransactionBase):
    pass


class FxTransactionUpdate(BaseModel):
    trade_date: Optional[date] = None
    type: Optional[Literal["BUY", "SELL", "SETTLEMENT"]] = None
    currency: Optional[Literal["KRW", "USD"]] = None
    fx_amount: Optional[float] = None
    krw_amount: Optional[float] = None
    rate: Optional[float] = None
    description: Optional[str] = None
    note: Optional[str] = None


class FxTransactionRead(FxTransactionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class SettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target_index_allocations: Optional[List[TargetIndexAllocation]] = None
    server_url: Optional[str] = None
    dividend_year: Optional[int] = None
    dividend_total: Optional[float] = None
    dividends: Optional[List[DividendRecord]] = None
    usd_fx_base: Optional[float] = None
    usd_fx_now: Optional[float] = None
    benchmark_name: Optional[str] = None
    benchmark_return: Optional[float] = None
    kis_app: Optional[str] = None
    kis_sec: Optional[str] = None
    kis_acct_stock: Optional[str] = None
    kis_prod: Optional[str] = None
    kis_htsid: Optional[str] = None
    kis_prod_url: Optional[str] = None
    kis_ops_url: Optional[str] = None
    kis_vps_url: Optional[str] = None
    kis_vops_url: Optional[str] = None
    kis_agent: Optional[str] = None


class SettingsUpdate(BaseModel):
    target_index_allocations: Optional[List[TargetIndexAllocation]] = None
    server_url: Optional[str] = None
    dividends: Optional[List[DividendRecord]] = None
    dividend_year: Optional[int] = None
    dividend_total: Optional[float] = None
    usd_fx_base: Optional[float] = None
    usd_fx_now: Optional[float] = None
    benchmark_name: Optional[str] = None
    benchmark_return: Optional[float] = None
    kis_app: Optional[str] = None
    kis_sec: Optional[str] = None
    kis_acct_stock: Optional[str] = None
    kis_prod: Optional[str] = None
    kis_htsid: Optional[str] = None
    kis_prod_url: Optional[str] = None
    kis_ops_url: Optional[str] = None
    kis_vps_url: Optional[str] = None
    kis_vops_url: Optional[str] = None
    kis_agent: Optional[str] = None


class DistributionItem(BaseModel):
    name: str
    value: float


class PortfolioSummary(BaseModel):
    total_value: float
    total_invested: float
    realized_profit_total: float
    unrealized_profit_total: float
    total_dividends: float = 0.0
    dividend_yearly: List[DividendRecord] = []
    category_distribution: List[DistributionItem] = []
    index_distribution: List[DistributionItem] = []
    xirr_rate: Optional[float] = None  # 연평균 수익률 (XIRR)


class PortfolioResponse(BaseModel):
    assets: List[AssetRead]
    trades: List[TradeRead]
    summary: PortfolioSummary


class PortfolioRestoreRequest(BaseModel):
    assets: List[AssetCreate]


class PortfolioRestoreResponse(BaseModel):
    restored: int
    deleted: int


class PortfolioSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    snapshot_at: datetime
    total_value: float
    total_invested: float
    realized_profit_total: float
    unrealized_profit_total: float


class TransactionResult(BaseModel):
    """간단한 트랜잭션 결과 표현: 향후 원자적 API 응답에서 사용."""
    success: bool = True
    applied: int = 0
    message: Optional[str] = None


# ========== YearlyCashflow (연도별 입출금) ==========

class YearlyCashflowBase(BaseModel):
    year: int
    deposit: float = 0.0
    withdrawal: float = 0.0
    note: Optional[str] = None


class YearlyCashflowCreate(YearlyCashflowBase):
    pass


class YearlyCashflowUpdate(BaseModel):
    year: Optional[int] = None
    deposit: Optional[float] = None
    withdrawal: Optional[float] = None
    note: Optional[str] = None


class YearlyCashflowRead(YearlyCashflowBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    net: float = 0.0  # deposit - withdrawal (계산된 값)
    created_at: datetime
    updated_at: datetime


# ========== ExternalCashflow (개별 입출금) ==========

class ExternalCashflowBase(BaseModel):
    date: date
    amount: float
    description: Optional[str] = None
    account_info: Optional[str] = None


class ExternalCashflowCreate(ExternalCashflowBase):
    pass


class ExternalCashflowUpdate(BaseModel):
    date: Optional[date] = None
    amount: Optional[float] = None
    description: Optional[str] = None
    account_info: Optional[str] = None


class ExternalCashflowRead(ExternalCashflowBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class ReportResponse(BaseModel):
    generated_at: datetime
    portfolio: PortfolioResponse
    snapshots: List[PortfolioSnapshotRead]
    fx_transactions: List[FxTransactionRead]
    external_cashflows: List[ExternalCashflowRead]
    settings: Optional[SettingsRead] = None


class MonthlyReportSummary(BaseModel):
    year: int
    month: int
    trade_count: int = 0
    trade_buy_value: float = 0.0
    trade_sell_value: float = 0.0
    cashflow_count: int = 0
    cashflow_total: float = 0.0
    fx_transaction_count: int = 0
    snapshot_count: int = 0


class QuarterlyReportSummary(BaseModel):
    year: int
    quarter: int
    trade_count: int = 0
    trade_buy_value: float = 0.0
    trade_sell_value: float = 0.0
    cashflow_count: int = 0
    cashflow_total: float = 0.0
    fx_transaction_count: int = 0
    snapshot_count: int = 0


class ReportPeriod(BaseModel):
    year: int
    month: Optional[int] = None
    quarter: Optional[int] = None
    half: Optional[int] = None
    start_date: date
    end_date: date


class ReportActivitySummary(BaseModel):
    trade_count: int = 0
    trade_buy_value: float = 0.0
    trade_sell_value: float = 0.0
    net_buy: float = 0.0
    cashflow_count: int = 0
    cashflow_total: float = 0.0
    deposit_total: float = 0.0
    withdrawal_total: float = 0.0
    net_flow: float = 0.0
    invested_principal: float = 0.0
    fx_transaction_count: int = 0
    snapshot_count: int = 0


class TopAssetSummary(BaseModel):
    id: int
    name: str
    ticker: Optional[str] = None
    category: str
    currency: str
    amount: float
    current_price: float
    purchase_price: Optional[float] = None
    value: float
    invested: float
    unrealized_profit: float
    unrealized_profit_rate: Optional[float] = None


class ReportAiResponse(BaseModel):
    generated_at: datetime
    period: ReportPeriod
    summary: PortfolioSummary
    activity: ReportActivitySummary
    top_assets: List[TopAssetSummary]


class ReportAiTextResponse(BaseModel):
    generated_at: datetime
    period: ReportPeriod
    report: str
    model: Optional[str] = None


# ========== Expense (소비 데이터) ==========

class ExpenseBase(BaseModel):
    date: date
    amount: float
    category: str
    merchant: Optional[str] = None
    method: Optional[str] = None
    is_fixed: bool = False
    memo: Optional[str] = None


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    date: Optional[date] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    merchant: Optional[str] = None
    method: Optional[str] = None
    is_fixed: Optional[bool] = None
    memo: Optional[str] = None


class ExpenseRead(ExpenseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    review_reason: Optional[str] = None
    review_suggested_category: Optional[str] = None

# ========== Scheduler (스케줄러 상태) ==========

class SchedulerStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    status: str
    last_run_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    message: Optional[str] = None
    updated_at: datetime
