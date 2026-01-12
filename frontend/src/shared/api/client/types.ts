/**
 * 백엔드 API 응답 타입 정의
 */

// --- CMA/Settings ---

export interface BackendCmaConfig {
    principal: number;
    annual_rate: number;
    tax_rate: number;
    start_date: string;
}

export interface BackendTargetIndexAllocation {
    index_group: string;
    target_weight: number;
}

export interface BackendSettings {
    target_index_allocations?: BackendTargetIndexAllocation[];
    server_url?: string | null;
    usd_fx_base?: number | null;
    usd_fx_now?: number | null;
    benchmark_name?: string | null;
    benchmark_return?: number | null;
}

// --- Assets ---

export interface BackendAsset {
    id: number;
    name: string;
    ticker?: string | null;
    category: string;
    currency: 'KRW' | 'USD';
    amount: number;
    current_price: number;
    purchase_price?: number | null;
    realized_profit: number;
    index_group?: string | null;
    cma_config?: BackendCmaConfig | null;
    created_at: string;
    updated_at: string;
}

export interface BackendRestoreAsset {
    name: string;
    ticker?: string | null;
    category: string;
    currency: 'KRW' | 'USD';
    amount: number;
    current_price: number;
    purchase_price?: number | null;
    realized_profit: number;
    index_group?: string | null;
    cma_config?: BackendCmaConfig | null;
}

// --- Trades ---

export interface BackendTrade {
    id: number;
    asset_id: number;
    asset_name?: string | null;
    asset_ticker?: string | null;
    user_id: number;
    type: 'BUY' | 'SELL';
    quantity: number;
    price: number;
    timestamp: string;
    realized_delta?: number | null;
    note?: string | null;
    created_at: string;
    updated_at: string;
}

// --- FX Transactions ---

export interface BackendFxTransaction {
    id: number;
    user_id: number;
    trade_date: string;
    type: 'BUY' | 'SELL' | 'SETTLEMENT';
    currency: 'KRW' | 'USD';
    fx_amount?: number | null;
    krw_amount?: number | null;
    rate?: number | null;
    description?: string | null;
    note?: string | null;
    created_at: string;
    updated_at: string;
}

// --- Portfolio ---

export interface BackendDistributionItem {
    name: string;
    value: number;
}

export interface BackendPortfolioSummary {
    total_value: number;
    total_invested: number;
    realized_profit_total: number;
    unrealized_profit_total: number;
    category_distribution: BackendDistributionItem[];
    index_distribution: BackendDistributionItem[];
    total_dividends?: number;
    dividend_yearly?: { year: number; total: number }[];
    xirr_rate?: number | null;
}

export interface BackendPortfolioResponse {
    assets: BackendAsset[];
    trades: BackendTrade[];
    summary: BackendPortfolioSummary;
}

export interface BackendPortfolioRestoreResponse {
    restored: number;
    deleted: number;
}

export interface BackendSnapshot {
    id: number;
    snapshot_at: string;
    total_value: number;
    total_invested: number;
    realized_profit_total: number;
    unrealized_profit_total: number;
}

export interface BackendExternalCashflow {
    id: number;
    user_id: number;
    date: string;
    amount: number;
    description?: string | null;
    account_info?: string | null;
    created_at: string;
    updated_at: string;
}

export interface BackendReportResponse {
    generated_at: string;
    portfolio: BackendPortfolioResponse;
    snapshots: BackendSnapshot[];
    fx_transactions: BackendFxTransaction[];
    external_cashflows: BackendExternalCashflow[];
    settings?: BackendSettings | null;
}

// --- Health & FX Rate ---

export interface BackendHealthResponse {
    status: string;
}

export interface BackendFxRateResponse {
    base: string;
    quote: string;
    rate: number;
}

// --- Cashflows ---

export interface BackendYearlyCashflow {
    id: number;
    year: number;
    deposit: number;
    withdrawal: number;
    net: number;
    note?: string | null;
    created_at: string;
    updated_at: string;
}

// --- Expenses ---

export interface BackendExpense {
    id: number;
    user_id: number;
    date: string;
    amount: number;
    category: string;
    merchant?: string | null;
    method?: string | null;
    is_fixed: boolean;
    memo?: string | null;
    review_reason?: string | null;
    review_suggested_category?: string | null;
    created_at: string;
    updated_at: string;
    deleted_at?: string | null;
}

export interface BackendExpenseUploadResult {
    success: boolean;
    total_rows: number;
    added: number;
    skipped: number;
    filename: string;
}

export interface BackendExpenseSummaryCategoryBreakdownItem {
    category: string;
    amount: number;
}

export interface BackendExpenseSummaryMethodBreakdownItem {
    method: string;
    amount: number;
}

export interface BackendExpenseSummaryResponse {
    period: { year: number | null; month: number | null };
    total_expense: number;
    total_income: number;
    net: number;
    fixed_expense: number;
    fixed_ratio: number;
    category_breakdown: BackendExpenseSummaryCategoryBreakdownItem[];
    method_breakdown: BackendExpenseSummaryMethodBreakdownItem[];
    transaction_count: number;
}

// --- Ticker Search ---

export interface BackendTickerInfo {
    symbol: string;
    name: string;
    exchange?: string | null;
    currency?: string | null;
    type?: string | null;
}

export interface BackendTickerSearchResponse {
    query: string;
    results: BackendTickerInfo[];
}

// --- AI Reports ---

export interface BackendAiReportTextResponse {
    generated_at: string;
    period: {
        year: number;
        month?: number | null;
        quarter?: number | null;
        half?: number | null;
        start_date: string;
        end_date: string;
    };
    report: string;
    model?: string | null;
}

export interface BackendSavedAiReport {
    id: number;
    period_year: number;
    period_month?: number | null;
    period_quarter?: number | null;
    period_half?: number | null;
    query: string;
    report: string;
    model?: string | null;
    generated_at: string;
    created_at: string;
}

// --- News ---

export interface BackendNewsArticle {
    id: number;
    title: string;
    url?: string | null;
    source_name?: string | null;
    published_at?: string | null;
    snippet: string;
}

export interface BackendNewsSearchResponse {
    query: string;
    count: number;
    articles: BackendNewsArticle[];
}
