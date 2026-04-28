# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
>
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
>
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
>
> ---
>
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | Remove explicit any usage in auth callback and portfolio backup validation test | P2 | ⬜ Pending |
| 2 | PROMPT-002 | Clean up TypeScript no-undef lint configuration and remove file-level disables | P2 | ⬜ Pending |

**Total: 2 prompts** | **Completed: 0** | **Remaining: 2**

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] Remove explicit any usage in auth callback and portfolio backup validation test

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Replace explicit `any` usage with type-safe alternatives in the auth callback flow and backup validation test fixtures.  
**Files to Modify**: `frontend/src/pages/AuthCallbackPage.tsx`, `frontend/test/portfolioBackupValidation.test.ts`

#### Instructions:

1. Open `frontend/src/pages/AuthCallbackPage.tsx` and replace its contents with the code below.
2. Open `frontend/test/portfolioBackupValidation.test.ts` and replace its contents with the code below.

#### Implementation Code:

```tsx
import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useSettings } from '../../hooks/SettingsContext';
import type { AppSettings } from '../../lib/types';

type NaverCallbackResponse = {
    access_token?: string;
    user?: AppSettings['naverUser'];
};

type NaverCallbackError = {
    detail?: string;
};

/**
 * 네이버 로그인 콜백 페이지
 *
 * 네이버 로그인 후 리다이렉트되는 페이지입니다.
 * URL의 code와 state를 받아서 백엔드로 전송하고 HttpOnly 쿠키를 발급받습니다.
 */
export const AuthCallbackPage: React.FC = () => {
    const [searchParams] = useSearchParams();
    const navigate = useNavigate();
    const { settings, setSettings } = useSettings();
    const [status, setStatus] = React.useState<'loading' | 'success' | 'error'>('loading');
    const [errorMessage, setErrorMessage] = React.useState<string>('');

    const calledRef = React.useRef(false);

    useEffect(() => {
        const handleCallback = async () => {
            if (calledRef.current) return;
            calledRef.current = true;

            const code = searchParams.get('code');
            const state = searchParams.get('state');
            const error = searchParams.get('error');
            const errorDescription = searchParams.get('error_description');

            if (error) {
                setStatus('error');
                setErrorMessage(errorDescription || '네이버 로그인 중 오류가 발생했습니다.');
                return;
            }

            if (!code || !state) {
                setStatus('error');
                setErrorMessage('인증 코드가 없습니다. 다시 로그인해주세요.');
                return;
            }

            try {
                const response = await fetch(
                    `${settings.serverUrl}/api/auth/naver/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
                    { credentials: 'include' }
                );

                if (!response.ok) {
                    const errorData: NaverCallbackError = await response
                        .json()
                        .catch((): NaverCallbackError => ({}));
                    throw new Error(errorData.detail || '로그인 처리 중 오류가 발생했습니다.');
                }

                const data: NaverCallbackResponse = await response.json();
                if (!data?.access_token) {
                    throw new Error('로그인 토큰을 받지 못했습니다. 다시 로그인해주세요.');
                }

                setSettings((prev) => ({
                    ...prev,
                    cookieAuth: true,
                    naverUser: data.user,
                }));

                setStatus('success');

                setTimeout(() => {
                    navigate('/');
                }, 1000);
            } catch (error: unknown) {
                setStatus('error');
                const message = error instanceof Error
                    ? error.message
                    : '알 수 없는 오류가 발생했습니다.';
                setErrorMessage(message);
            }
        };

        void handleCallback();
    }, [searchParams, settings.serverUrl, setSettings, navigate]);

    if (status === 'loading') {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100">
                <div className="text-center">
                    <div className="inline-block animate-spin rounded-full h-16 w-16 border-t-4 border-b-4 border-indigo-600 mb-4"></div>
                    <h2 className="text-2xl font-bold text-slate-800 mb-2">로그인 처리 중...</h2>
                    <p className="text-slate-600">잠시만 기다려주세요.</p>
                </div>
            </div>
        );
    }

    if (status === 'success') {
        return (
            <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-green-50 to-emerald-100">
                <div className="text-center">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-green-500 rounded-full mb-4">
                        <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-slate-800 mb-2">로그인 성공!</h2>
                    <p className="text-slate-600">메인 페이지로 이동합니다...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-red-50 to-rose-100">
            <div className="max-w-md w-full bg-white rounded-2xl shadow-lg p-8">
                <div className="text-center mb-6">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-red-500 rounded-full mb-4">
                        <svg className="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </div>
                    <h2 className="text-2xl font-bold text-slate-800 mb-2">로그인 실패</h2>
                    <p className="text-slate-600 mb-4">{errorMessage}</p>
                    <button
                        onClick={() => navigate('/settings')}
                        className="px-6 py-3 bg-indigo-600 text-white rounded-lg font-semibold hover:bg-indigo-700 transition-colors"
                    >
                        설정으로 돌아가기
                    </button>
                </div>
            </div>
        </div>
    );
};
```

```ts
import { describe, expect, it } from 'vitest';
import { AssetCategory } from '../lib/types';
import { validateImportedAssetSnapshotList } from '@/features/portfolio';
import type { ImportedAssetSnapshot } from '@/shared/portfolio';

const asSnapshot = (value: Record<string, unknown>): ImportedAssetSnapshot =>
  value as unknown as ImportedAssetSnapshot;

describe('validateImportedAssetSnapshotList', () => {
  it('rejects empty input', () => {
    const result = validateImportedAssetSnapshotList([]);
    expect(result.valid).toHaveLength(0);
    expect(result.errors).toHaveLength(1);
  });

  it('rejects invalid category/amount/currentPrice', () => {
    const result = validateImportedAssetSnapshotList([
      asSnapshot({
        name: 'A',
        category: 'INVALID',
        amount: 1,
        currentPrice: 100,
        currency: 'KRW',
      }),
      asSnapshot({
        name: 'B',
        category: AssetCategory.STOCK_KR,
        amount: 0,
        currentPrice: 100,
        currency: 'KRW',
      }),
      asSnapshot({
        name: 'C',
        category: AssetCategory.STOCK_KR,
        amount: 1,
        currentPrice: Number.NaN,
        currency: 'KRW',
      }),
    ]);

    expect(result.valid).toHaveLength(0);
    expect(result.errors.length).toBeGreaterThanOrEqual(3);
  });

  it('normalizes ticker and infers currency when missing or invalid', () => {
    const result = validateImportedAssetSnapshotList([
      asSnapshot({
        name: '  Apple ',
        ticker: '  AAPL ',
        category: AssetCategory.STOCK_US,
        amount: 1,
        currentPrice: 100,
        currency: 'NOPE',
      }),
    ]);

    expect(result.errors).toHaveLength(0);
    expect(result.valid[0]?.name).toBe('Apple');
    expect(result.valid[0]?.ticker).toBe('AAPL');
    expect(result.valid[0]?.currency).toBe('USD');
  });

  it('emits warnings for invalid numeric fields and duplicates', () => {
    const result = validateImportedAssetSnapshotList([
      asSnapshot({
        name: 'Samsung',
        ticker: '005930',
        category: AssetCategory.STOCK_KR,
        amount: 1,
        currentPrice: 10,
        purchasePrice: -1,
        realizedProfit: 'x',
        currency: 'KRW',
      }),
      asSnapshot({
        name: 'Samsung',
        ticker: '005930',
        category: AssetCategory.STOCK_KR,
        amount: 1,
        currentPrice: 10,
        currency: 'KRW',
      }),
    ]);

    expect(result.errors).toHaveLength(0);
    expect(result.warnings.length).toBeGreaterThanOrEqual(2);
  });
});
```

#### Verification:
- Run: `npm run test --prefix frontend`
- Expected: All frontend tests pass without `no-explicit-any` violations in the modified files.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

### [PROMPT-002] Clean up TypeScript no-undef lint configuration and remove file-level disables

**⏱️ Execute this prompt now, then proceed to final verification**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Move the `no-undef` exception into ESLint configuration so TypeScript files no longer need file-level disable comments.  
**Files to Modify**: `eslint.config.js`, `frontend/src/shared/api/client/core.ts`, `frontend/src/shared/api/client/client.ts`, `frontend/test/apiClient.test.ts`

#### Instructions:

1. Open `eslint.config.js` and replace its contents with the code below.
2. Open `frontend/src/shared/api/client/core.ts` and replace its contents with the code below.
3. Open `frontend/src/shared/api/client/client.ts` and replace its contents with the code below.
4. Open `frontend/test/apiClient.test.ts` and replace its contents with the code below.

#### Implementation Code:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import globals from "globals";

export default tseslint.config(
    {
        ignores: [
            "**/dist/**",
            "**/node_modules/**",
            "**/venv/**",
            "**/.venv/**",
            "**/*.pyc",
            "**/__pycache__/**",
            "**/.output/**",
            "**/build/**",
            "**/out/**"
        ]
    },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    {
        files: ["**/*.{ts,tsx}"],
        languageOptions: {
            globals: {
                ...globals.browser,
                ...globals.node
            }
        },
        rules: {
            "@typescript-eslint/no-explicit-any": "error",
            "@typescript-eslint/no-unused-vars": "warn",
            "no-undef": "off"
        },
    },
    {
        files: ["**/types.ts"],
        rules: {
            "@typescript-eslint/no-explicit-any": "off"
        }
    }
);
```

```ts
export type RequestFn = <T>(endpoint: string, options?: RequestInit) => Promise<T>;
export type CreateHeadersFn = (withJson?: boolean) => HeadersInit;
```

```ts
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
    BackendAssetUpdatePayload,
    BackendAssetCreatePayload,
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
            headers['X-API-Key'] = this.apiToken;
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
            response = await fetch(url, { ...options, headers, credentials: 'include' });
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

        if (response.status === 204) {
            return {} as T;
        }

        try {
            return await response.json();
        } catch {
            return {} as T;
        }
    }

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

    async checkHealth(): Promise<BackendHealthResponse> {
        return checkHealth(this.requestFn);
    }

    async fetchSettings(): Promise<BackendSettings> {
        return fetchSettings(this.requestFn);
    }

    async updateSettings(payload: BackendSettings): Promise<BackendSettings> {
        return updateSettings(this.requestFn, payload);
    }

    async createAsset(payload: BackendAssetCreatePayload): Promise<BackendAsset> {
        return createAsset(this.requestFn, payload);
    }

    async deleteAsset(assetId: number): Promise<void> {
        return deleteAsset(this.requestFn, assetId);
    }

    async updateAsset(assetId: number, payload: BackendAssetUpdatePayload): Promise<BackendAsset> {
        return updateAsset(this.requestFn, assetId, payload);
    }

    async fetchPrices(tickers: string[]): Promise<Record<string, number>> {
        return fetchPrices(this.requestFn, tickers);
    }

    async fetchUsdKrwFxRate(fresh = false): Promise<BackendFxRateResponse> {
        return fetchUsdKrwFxRate(this.requestFn, fresh);
    }

    async searchTicker(query: string): Promise<BackendTickerSearchResponse> {
        return searchTicker(this.requestFn, query);
    }

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
```

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, type BackendHealthResponse, type BackendPortfolioResponse } from '@/shared/api/client';

describe('ApiClient', () => {
  const baseUrl = 'http://localhost:8000';
  const token = 'test-token';
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock as unknown as typeof fetch);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('checkHealth calls /api/health with token', async () => {
    const client = new ApiClient(baseUrl, token);
    const mockResponse: BackendHealthResponse = { status: 'ok' };
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => mockResponse,
    } as Response);

    const result = await client.checkHealth();

    expect(result).toEqual(mockResponse);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${baseUrl}/api/health`);
    expect(options).toMatchObject({ method: 'GET' });
    expect((options as RequestInit).headers).toMatchObject({ 'X-API-Token': token });
  });

  it('fetchPortfolio calls /api/portfolio', async () => {
    const client = new ApiClient(baseUrl, token);
    const mockData: BackendPortfolioResponse = {
      assets: [],
      trades: [],
      summary: {
        total_value: 1000,
        total_invested: 900,
        realized_profit_total: 0,
        unrealized_profit_total: 100,
        category_distribution: [],
        index_distribution: [],
      },
    };
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => mockData,
    } as Response);

    const result = await client.fetchPortfolio();

    expect(result).toEqual(mockData);
    expect(fetchMock).toHaveBeenCalledWith(`${baseUrl}/api/portfolio`, expect.anything());
  });

  it('fetchExpenses builds query params', async () => {
    const client = new ApiClient(baseUrl, token);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => [],
    } as Response);

    await client.fetchExpenses({ year: 2025, month: 1, category: 'Food', includeDeleted: true });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/expenses/?');
    expect(url).toContain('year=2025');
    expect(url).toContain('month=1');
    expect(url).toContain('category=Food');
    expect(url).toContain('include_deleted=true');
  });

  it('deleteExpense uses DELETE', async () => {
    const client = new ApiClient(baseUrl, token);
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 204,
      statusText: 'No Content',
      text: async () => '',
    } as Response);

    await client.deleteExpense(123);

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${baseUrl}/api/expenses/123`);
    expect(options).toMatchObject({ method: 'DELETE' });
  });

  it('throws ApiError when response is not ok', async () => {
    const client = new ApiClient(baseUrl, token);
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      text: async () => 'boom',
    } as Response);

    await expect(client.checkHealth()).rejects.toBeInstanceOf(ApiError);
  });
});
```

#### Verification:
- Run: `npx eslint eslint.config.js frontend/src/shared/api/client/core.ts frontend/src/shared/api/client/client.ts frontend/test/apiClient.test.ts`
- Expected: No `no-undef` errors and no file-level disable comments remain in the modified TypeScript files.

**🎉 ALL PROMPTS COMPLETED! Run final verification.**
