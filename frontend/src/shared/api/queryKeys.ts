/**
 * Query Keys
 * 
 * React Query의 쿼리 키를 중앙에서 관리합니다.
 * 일관된 키 구조로 캐시 무효화가 쉬워집니다.
 */

export const queryKeys = {
    // Portfolio
    portfolio: ['portfolio'] as const,
    legacyPortfolio: ['legacyPortfolio'] as const,
    assets: ['assets'] as const,
    asset: (id: number) => ['assets', id] as const,

    // Trades
    trades: ['trades'] as const,
    tradesForAsset: (assetId: number) => ['trades', { assetId }] as const,

    // Snapshots (히스토리)
    snapshots: (days?: number) => ['snapshots', { days }] as const,

    // Cashflows
    cashflows: ['cashflows'] as const,

    // Expenses
    expenses: (params?: { year?: number; month?: number; category?: string }) =>
        ['expenses', params] as const,
    expenseCategories: ['expenses', 'categories'] as const,

    // FX Transactions
    fxTransactions: (params?: { kind?: string; startDate?: string; endDate?: string }) =>
        ['fxTransactions', params] as const,

    // FX Rate
    fxRate: ['fxRate', 'usdkrw'] as const,

    // Settings
    settings: ['settings'] as const,

    // Reports
    report: (params: { year: number; month?: number; quarter?: number }) =>
        ['report', params] as const,
    aiReport: (params: { year?: number; month?: number; quarter?: number; query?: string }) =>
        ['aiReport', params] as const,
    savedReports: ['savedReports'] as const,
} as const;
