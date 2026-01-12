import type { TradeType, FxTransactionType } from '@lib/types';
import { NetworkError, ApiError } from './errors';
import type {
    BackendPortfolioResponse,
    BackendRestoreAsset,
    BackendPortfolioRestoreResponse,
    BackendSnapshot,
    BackendHealthResponse,
    BackendSettings,
    BackendAsset,
    BackendFxRateResponse,
    BackendTickerSearchResponse,
    BackendTrade,
    BackendFxTransaction,
    BackendYearlyCashflow,
    BackendAiReportTextResponse,
    BackendExpense,
    BackendExpenseUploadResult,
    BackendExpenseSummaryResponse,
    BackendReportResponse,
    BackendSavedAiReport,
    BackendNewsSearchResponse,
} from './types';
import type { CreateHeadersFn, RequestFn } from './core';
import { fetchPortfolio, restorePortfolio, fetchSnapshots, createSnapshot } from './portfolio';
import { checkHealth } from './health';
import { fetchSettings, updateSettings } from './settings';
import {
    createAsset,
    deleteAsset,
    updateAsset,
    fetchPrices,
    fetchUsdKrwFxRate,
    searchTicker,
} from './assets';
import { fetchTrades, createTrade } from './trades';
import {
    fetchFxTransactions,
    createFxTransaction,
    updateFxTransaction,
    deleteFxTransaction,
} from './fx';
import {
    fetchCashflows,
    createCashflow,
    updateCashflow,
    deleteCashflow,
    uploadStatement,
} from './cashflows';
import {
    fetchReport,
    fetchAiReportText,
    fetchAiReportTextStream,
    fetchSavedReports,
    saveReport,
    deleteReport,
} from './reports';
import {
    fetchCategories,
    triggerLearning,
    fetchExpenses,
    fetchExpenseSummary,
    deleteExpense,
    restoreExpense,
    updateExpense,
    uploadExpenseFile,
} from './expenses';

export class ApiClient {
    private readonly baseUrl: string;
    private readonly requestFn: RequestFn;

    constructor(baseUrl: string, private apiToken?: string) {
        let trimmed = baseUrl.replace(/\/+$/, '');

        // Vercel(HTTPS)에서 HTTP 호출 시 Mixed Content 에러 방지용 자동 업그레이드
        if (typeof window !== 'undefined' && window.location.protocol === 'https:' && trimmed.startsWith('http://')) {
            console.warn('Mixed Content detected: Upgrading serverUrl to HTTPS for secure connection');
            trimmed = trimmed.replace(/^http:\/\//, 'https://');
        }

        this.baseUrl = trimmed.endsWith('/api')
            ? trimmed.slice(0, -4)
            : trimmed;
        this.requestFn = (endpoint, options) => this.request(endpoint, options);
    }

    private createHeaders(withJson = false): HeadersInit {
        const headers: HeadersInit = withJson
            ? { 'Content-Type': 'application/json' }
            : {};
        if (this.apiToken) {
            headers['X-API-Token'] = this.apiToken;
        }
        return headers;
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {},
    ): Promise<T> {
        const url = `${this.baseUrl}${endpoint}`;
        const isFormData = options.body instanceof FormData;
        const headers = {
            ...this.createHeaders(
                options.method !== 'GET' && options.method !== 'DELETE' && !isFormData,
            ),
            ...(options.headers || {}),
        };

        let response: Response;
        try {
            response = await fetch(url, { ...options, headers });
        } catch (error) {
            // AbortError는 정상적인 요청 취소이므로 그대로 throw
            if (error instanceof Error && error.name === 'AbortError') {
                throw error;
            }
            throw new NetworkError(url, error);
        }

        if (!response.ok) {
            const errorText = await response.text();
            throw new ApiError(response.status, response.statusText, url, errorText);
        }

        // DELETE 등 응답이 없는 경우가 있을 수 있음
        if (response.status === 204) {
            return {} as T;
        }

        try {
            return await response.json();
        } catch {
            return {} as T;
        }
    }

    // --- Portfolio ---

    async fetchPortfolio(): Promise<BackendPortfolioResponse> {
        return fetchPortfolio(this.requestFn);
    }

    async restorePortfolio(
        assets: BackendRestoreAsset[],
    ): Promise<BackendPortfolioRestoreResponse> {
        return restorePortfolio(this.requestFn, assets);
    }

    async fetchSnapshots(days = 180): Promise<BackendSnapshot[]> {
        return fetchSnapshots(this.requestFn, days);
    }

    async createSnapshot(): Promise<BackendSnapshot> {
        return createSnapshot(this.requestFn);
    }

    // --- Health ---

    async checkHealth(): Promise<BackendHealthResponse> {
        return checkHealth(this.requestFn);
    }

    // --- Settings ---

    async fetchSettings(): Promise<BackendSettings> {
        return fetchSettings(this.requestFn);
    }

    async updateSettings(payload: BackendSettings): Promise<BackendSettings> {
        return updateSettings(this.requestFn, payload);
    }

    // --- Assets ---

    async createAsset(payload: any): Promise<BackendAsset> {
        return createAsset(this.requestFn, payload);
    }

    async deleteAsset(assetId: number): Promise<void> {
        return deleteAsset(this.requestFn, assetId);
    }

    async updateAsset(assetId: number, payload: any): Promise<BackendAsset> {
        return updateAsset(this.requestFn, assetId, payload);
    }

    async fetchPrices(tickers: string[]): Promise<Record<string, number>> {
        return fetchPrices(this.requestFn, tickers);
    }

    async fetchUsdKrwFxRate(): Promise<BackendFxRateResponse> {
        return fetchUsdKrwFxRate(this.requestFn);
    }

    async searchTicker(query: string): Promise<BackendTickerSearchResponse> {
        return searchTicker(this.requestFn, query);
    }

    // --- Trades ---

    async fetchTrades(params?: {
        limit?: number;
        beforeId?: number;
        assetId?: number;
    }): Promise<BackendTrade[]> {
        return fetchTrades(this.requestFn, params);
    }

    async createTrade(
        assetId: number,
        type: TradeType,
        quantity: number,
        price: number,
    ): Promise<BackendTrade> {
        return createTrade(this.requestFn, assetId, type, quantity, price);
    }

    // --- FX Transactions ---

    async fetchFxTransactions(params?: {
        limit?: number;
        beforeId?: number;
        kind?: FxTransactionType;
        startDate?: string;
        endDate?: string;
    }): Promise<BackendFxTransaction[]> {
        return fetchFxTransactions(this.requestFn, params);
    }

    async createFxTransaction(payload: {
        trade_date: string;
        type: FxTransactionType;
        currency: 'KRW' | 'USD';
        fx_amount?: number | null;
        krw_amount?: number | null;
        rate?: number | null;
        description?: string | null;
        note?: string | null;
    }): Promise<BackendFxTransaction> {
        return createFxTransaction(this.requestFn, payload);
    }

    async updateFxTransaction(
        recordId: number,
        payload: {
            trade_date?: string;
            type?: FxTransactionType;
            currency?: 'KRW' | 'USD';
            fx_amount?: number | null;
            krw_amount?: number | null;
            rate?: number | null;
            description?: string | null;
            note?: string | null;
        },
    ): Promise<BackendFxTransaction> {
        return updateFxTransaction(this.requestFn, recordId, payload);
    }

    async deleteFxTransaction(recordId: number): Promise<void> {
        return deleteFxTransaction(this.requestFn, recordId);
    }

    // --- Yearly Cashflows (연도별 입출금) ---

    async fetchCashflows(): Promise<BackendYearlyCashflow[]> {
        return fetchCashflows(this.requestFn);
    }

    async createCashflow(payload: {
        year: number;
        deposit: number;
        withdrawal: number;
        note?: string | null;
    }): Promise<BackendYearlyCashflow> {
        return createCashflow(this.requestFn, payload);
    }

    async updateCashflow(
        cashflowId: number,
        payload: {
            year?: number;
            deposit?: number;
            withdrawal?: number;
            note?: string | null;
        },
    ): Promise<BackendYearlyCashflow> {
        return updateCashflow(this.requestFn, cashflowId, payload);
    }

    async deleteCashflow(cashflowId: number): Promise<void> {
        return deleteCashflow(this.requestFn, cashflowId);
    }

    async uploadStatement(file: File): Promise<{
        message: string;
        added: number;
        skipped: number;
        total_parsed: number;
    }> {
        return uploadStatement(this.requestFn, file);
    }

    // --- Reports ---

    async fetchReport(params: {
        year: number;
        month?: number;
        quarter?: number;
        half?: number;
    }): Promise<BackendReportResponse> {
        return fetchReport(this.requestFn, params);
    }

    async fetchAiReportText(params: {
        year?: number;
        month?: number;
        quarter?: number;
        query?: string;
        maxTokens?: number;
        model?: string;
    }): Promise<BackendAiReportTextResponse> {
        return fetchAiReportText(this.requestFn, params);
    }

    async fetchAiReportTextStream(
        params: {
            year?: number;
            month?: number;
            quarter?: number;
            query?: string;
            maxTokens?: number;
            model?: string;
        },
        handlers: {
            onMeta: (meta: Omit<BackendAiReportTextResponse, 'report'>) => void;
            onChunk: (chunk: string) => void;
        },
    ): Promise<void> {
        const createHeaders: CreateHeadersFn = (withJson = false) => this.createHeaders(withJson);
        return fetchAiReportTextStream(this.baseUrl, createHeaders, params, handlers);
    }

    // --- Expenses ---

    async fetchCategories(): Promise<string[]> {
        return fetchCategories(this.requestFn);
    }

    async triggerLearning(): Promise<{ added: number; updated: number }> {
        return triggerLearning(this.requestFn);
    }

    async fetchExpenses(params?: {
        year?: number;
        month?: number;
        category?: string;
        includeDeleted?: boolean;
    }, options: { signal?: AbortSignal } = {}): Promise<BackendExpense[]> {
        return fetchExpenses(this.requestFn, params, options);
    }

    async fetchExpenseSummary(params?: {
        year?: number;
        month?: number;
    }, options: { signal?: AbortSignal } = {}): Promise<BackendExpenseSummaryResponse> {
        return fetchExpenseSummary(this.requestFn, params, options);
    }

    async deleteExpense(expenseId: number): Promise<{ status: string; deleted_at?: string | null }> {
        return deleteExpense(this.requestFn, expenseId);
    }

    async restoreExpense(expenseId: number): Promise<BackendExpense> {
        return restoreExpense(this.requestFn, expenseId);
    }

    async updateExpense(expenseId: number, payload: Partial<BackendExpense>): Promise<BackendExpense> {
        return updateExpense(this.requestFn, expenseId, payload);
    }

    async uploadExpenseFile(file: File): Promise<BackendExpenseUploadResult> {
        return uploadExpenseFile(this.requestFn, file);
    }

    // --- Saved AI Reports ---

    async fetchSavedReports(): Promise<BackendSavedAiReport[]> {
        return fetchSavedReports(this.requestFn);
    }

    async saveReport(payload: {
        period_year: number;
        period_month?: number | null;
        period_quarter?: number | null;
        period_half?: number | null;
        query: string;
        report: string;
        model?: string | null;
        generated_at: string;
    }): Promise<BackendSavedAiReport> {
        return saveReport(this.requestFn, payload);
    }

    async deleteReport(reportId: number): Promise<void> {
        return deleteReport(this.requestFn, reportId);
    }

    // --- News ---

    async searchNews(query: string, ticker?: string): Promise<BackendNewsSearchResponse> {
        let url = `/api/news/search?query=${encodeURIComponent(query)}`;
        if (ticker) {
            url += `&ticker=${encodeURIComponent(ticker)}`;
        }
        return this.requestFn(url, {
            method: 'GET',
        });
    }
}
