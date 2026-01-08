/**
 * API 클라이언트 - 백엔드 통신 담당
 */

import type { TradeType, FxTransactionType } from '../types';
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
    BackendReportResponse,
    BackendSavedAiReport,
} from './types';

export class ApiClient {
    private readonly baseUrl: string;

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
        return this.request<BackendPortfolioResponse>('/api/portfolio', {
            method: 'GET',
        });
    }

    async restorePortfolio(
        assets: BackendRestoreAsset[],
    ): Promise<BackendPortfolioRestoreResponse> {
        return this.request<BackendPortfolioRestoreResponse>('/api/portfolio/restore', {
            method: 'POST',
            body: JSON.stringify({ assets }),
        });
    }

    async fetchSnapshots(days = 180): Promise<BackendSnapshot[]> {
        return this.request<BackendSnapshot[]>(
            `/api/portfolio/snapshots?days=${days}`,
            { method: 'GET' },
        );
    }

    async createSnapshot(): Promise<BackendSnapshot> {
        return this.request<BackendSnapshot>('/api/portfolio/snapshots', {
            method: 'POST',
        });
    }

    // --- Health ---

    async checkHealth(): Promise<BackendHealthResponse> {
        return this.request<BackendHealthResponse>('/api/health', { method: 'GET' });
    }

    // --- Settings ---

    async fetchSettings(): Promise<BackendSettings> {
        return this.request<BackendSettings>('/api/settings', { method: 'GET' });
    }

    async updateSettings(payload: BackendSettings): Promise<BackendSettings> {
        return this.request<BackendSettings>('/api/settings', {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
    }

    // --- Assets ---

    async createAsset(payload: any): Promise<BackendAsset> {
        return this.request<BackendAsset>('/api/assets', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    }

    async deleteAsset(assetId: number): Promise<void> {
        return this.request<void>(`/api/assets/${assetId}`, {
            method: 'DELETE',
        });
    }

    async updateAsset(assetId: number, payload: any): Promise<BackendAsset> {
        return this.request<BackendAsset>(`/api/assets/${assetId}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
        });
    }

    async fetchPrices(tickers: string[]): Promise<Record<string, number>> {
        return this.request<Record<string, number>>('/api/kis/prices', {
            method: 'POST',
            body: JSON.stringify({ tickers }),
        });
    }

    async fetchUsdKrwFxRate(): Promise<BackendFxRateResponse> {
        return this.request<BackendFxRateResponse>('/api/kis/fx/usdkrw', { method: 'GET' });
    }

    async searchTicker(query: string): Promise<BackendTickerSearchResponse> {
        const q = query.trim();
        return this.request<BackendTickerSearchResponse>(
            `/api/search_ticker?q=${encodeURIComponent(q)}`,
            { method: 'GET' },
        );
    }

    // --- Trades ---

    async fetchTrades(params?: {
        limit?: number;
        beforeId?: number;
        assetId?: number;
    }): Promise<BackendTrade[]> {
        const search = new URLSearchParams();
        if (params?.limit != null) search.set('limit', params.limit.toString());
        if (params?.beforeId != null) search.set('before_id', params.beforeId.toString());
        if (params?.assetId != null) search.set('asset_id', params.assetId.toString());
        const qs = search.toString();
        return this.request<BackendTrade[]>(`/api/trades${qs ? `?${qs}` : ''}`, { method: 'GET' });
    }

    async createTrade(
        assetId: number,
        type: TradeType,
        quantity: number,
        price: number,
    ): Promise<BackendTrade> {
        return this.request<BackendTrade>(`/api/assets/${assetId}/trades`, {
            method: 'POST',
            body: JSON.stringify({
                asset_id: assetId,
                type,
                quantity,
                price,
            }),
        });
    }

    // --- FX Transactions ---

    async fetchFxTransactions(params?: {
        limit?: number;
        beforeId?: number;
        kind?: FxTransactionType;
        startDate?: string;
        endDate?: string;
    }): Promise<BackendFxTransaction[]> {
        const search = new URLSearchParams();
        if (params?.limit != null) search.set('limit', params.limit.toString());
        if (params?.beforeId != null) search.set('before_id', params.beforeId.toString());
        if (params?.kind != null) search.set('kind', params.kind);
        if (params?.startDate) search.set('start_date', params.startDate);
        if (params?.endDate) search.set('end_date', params.endDate);
        const qs = search.toString();
        return this.request<BackendFxTransaction[]>(`/api/exchanges${qs ? `?${qs}` : ''}`, {
            method: 'GET',
        });
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
        return this.request<BackendFxTransaction>('/api/exchanges', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
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
        return this.request<BackendFxTransaction>(`/api/exchanges/${recordId}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
        });
    }

    async deleteFxTransaction(recordId: number): Promise<void> {
        return this.request<void>(`/api/exchanges/${recordId}`, {
            method: 'DELETE',
        });
    }

    // --- Yearly Cashflows (연도별 입출금) ---

    async fetchCashflows(): Promise<BackendYearlyCashflow[]> {
        return this.request<BackendYearlyCashflow[]>('/api/cashflows', { method: 'GET' });
    }

    async createCashflow(payload: {
        year: number;
        deposit: number;
        withdrawal: number;
        note?: string | null;
    }): Promise<BackendYearlyCashflow> {
        return this.request<BackendYearlyCashflow>('/api/cashflows', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
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
        return this.request<BackendYearlyCashflow>(`/api/cashflows/${cashflowId}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
        });
    }

    async deleteCashflow(cashflowId: number): Promise<void> {
        return this.request<void>(`/api/cashflows/${cashflowId}`, {
            method: 'DELETE',
        });
    }

    async uploadStatement(file: File): Promise<{
        message: string;
        added: number;
        skipped: number;
        total_parsed: number;
    }> {
        const formData = new FormData();
        formData.append('file', file);

        return this.request<{
            message: string;
            added: number;
            skipped: number;
            total_parsed: number;
        }>('/api/cashflows/upload', {
            method: 'POST',
            body: formData,
            headers: {},
        });
    }

    // --- Reports ---

    async fetchReport(params: {
        year: number;
        month?: number;
        quarter?: number;
        half?: number;
    }): Promise<BackendReportResponse> {
        const search = new URLSearchParams();
        search.set('year', params.year.toString());

        if (params.month != null) {
            search.set('month', params.month.toString());
            return this.request<BackendReportResponse>(
                `/api/report/monthly?${search.toString()}`,
                { method: 'GET' },
            );
        }

        if (params.quarter != null) {
            search.set('quarter', params.quarter.toString());
            return this.request<BackendReportResponse>(
                `/api/report/quarterly?${search.toString()}`,
                { method: 'GET' },
            );
        }

        return this.request<BackendReportResponse>(
            `/api/report/yearly?${search.toString()}`,
            { method: 'GET' },
        );
    }

    async fetchAiReportText(params: {
        year?: number;
        month?: number;
        quarter?: number;
        query?: string;
        maxTokens?: number;
        model?: string;
    }): Promise<BackendAiReportTextResponse> {
        const search = new URLSearchParams();
        if (params.year != null) search.set('year', params.year.toString());
        if (params.month != null) search.set('month', params.month.toString());
        if (params.quarter != null) search.set('quarter', params.quarter.toString());
        if (params.query) search.set('query', params.query);
        if (params.maxTokens != null) search.set('max_tokens', params.maxTokens.toString());
        if (params.model) search.set('model', params.model);
        return this.request<BackendAiReportTextResponse>(
            `/api/report/ai/text?${search.toString()}`,
            { method: 'GET' },
        );
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
        const search = new URLSearchParams();
        if (params.year != null) search.set('year', params.year.toString());
        if (params.month != null) search.set('month', params.month.toString());
        if (params.quarter != null) search.set('quarter', params.quarter.toString());
        if (params.query) search.set('query', params.query);
        if (params.maxTokens != null) search.set('max_tokens', params.maxTokens.toString());
        if (params.model) search.set('model', params.model);

        const url = `${this.baseUrl}/api/report/ai/text/stream?${search.toString()}`;
        let response: Response;
        try {
            response = await fetch(url, {
                method: 'GET',
                headers: {
                    ...this.createHeaders(false),
                    Accept: 'text/event-stream',
                },
            });
        } catch (error) {
            if (error instanceof Error && error.name === 'AbortError') {
                throw error;
            }
            throw new NetworkError(url, error);
        }

        if (!response.ok) {
            const errorText = await response.text();
            throw new ApiError(response.status, response.statusText, url, errorText);
        }

        if (!response.body) {
            throw new ApiError(500, 'Stream response body is empty', url);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        const handleEvent = (rawEvent: string) => {
            const lines = rawEvent.split('\n');
            let event = 'message';
            const dataLines: string[] = [];
            for (const line of lines) {
                if (line.startsWith('event:')) {
                    event = line.replace('event:', '').trim();
                } else if (line.startsWith('data:')) {
                    dataLines.push(line.replace('data:', '').trimStart());
                }
            }
            const data = dataLines.join('\n');
            if (!data && event !== 'done') {
                return;
            }
            if (event === 'meta') {
                const parsed = JSON.parse(data) as Omit<BackendAiReportTextResponse, 'report'>;
                handlers.onMeta(parsed);
                return;
            }
            if (event === 'chunk') {
                handlers.onChunk(data);
                return;
            }
            if (event === 'error') {
                throw new Error(data || 'AI report stream failed');
            }
        };

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split('\n\n');
            buffer = parts.pop() ?? '';
            for (const part of parts) {
                if (part.trim()) {
                    handleEvent(part);
                }
            }
        }
    }

    // --- Expenses ---

    async fetchCategories(): Promise<string[]> {
        return this.request<string[]>('/api/expenses/categories');
    }

    async triggerLearning(): Promise<{ added: number; updated: number }> {
        return this.request<{ added: number; updated: number }>('/api/expenses/learn', {
            method: 'POST',
        });
    }

    async fetchExpenses(params?: {
        year?: number;
        month?: number;
        category?: string;
        includeDeleted?: boolean;
    }, options: { signal?: AbortSignal } = {}): Promise<BackendExpense[]> {
        const search = new URLSearchParams();
        if (params?.year != null) search.set('year', params.year.toString());
        if (params?.month != null) search.set('month', params.month.toString());
        if (params?.category) search.set('category', params.category);
        if (params?.includeDeleted) search.set('include_deleted', 'true');
        const qs = search.toString();
        return this.request<BackendExpense[]>(`/api/expenses${qs ? `?${qs}` : ''}`, {
            method: 'GET',
            signal: options.signal,
        });
    }

    async deleteExpense(expenseId: number): Promise<{ status: string; deleted_at?: string | null }> {
        return this.request<{ status: string; deleted_at?: string | null }>(`/api/expenses/${expenseId}`, {
            method: 'DELETE',
        });
    }

    async restoreExpense(expenseId: number): Promise<BackendExpense> {
        return this.request<BackendExpense>(`/api/expenses/${expenseId}/restore`, {
            method: 'POST',
        });
    }

    async updateExpense(expenseId: number, payload: Partial<BackendExpense>): Promise<BackendExpense> {
        return this.request<BackendExpense>(`/api/expenses/${expenseId}`, {
            method: 'PATCH',
            body: JSON.stringify(payload),
        });
    }

    async uploadExpenseFile(file: File): Promise<BackendExpenseUploadResult> {
        const formData = new FormData();
        formData.append('file', file);

        return this.request<BackendExpenseUploadResult>('/api/expenses/upload', {
            method: 'POST',
            body: formData,
            headers: {},
        });
    }

    // --- Saved AI Reports ---

    async fetchSavedReports(): Promise<BackendSavedAiReport[]> {
        return this.request<BackendSavedAiReport[]>('/api/report/saved', { method: 'GET' });
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
        return this.request<BackendSavedAiReport>('/api/report/saved', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
    }

    async deleteReport(reportId: number): Promise<void> {
        return this.request<void>(`/api/report/saved/${reportId}`, {
            method: 'DELETE',
        });
    }
}
