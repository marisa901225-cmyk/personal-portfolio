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
| 1 | PROMPT-001 | Remove explicit any usage in auth callback and portfolio backup tests | P2 | ⬜ Pending |
| 2 | PROMPT-002 | Clean up ESLint no-undef config and remove file-level disables | P2 | ⬜ Pending |
| 3 | PROMPT-003 | Add limit parameter support to news search API | P3 | ⬜ Pending |

**Total: 3 prompts** | **Completed: 0** | **Remaining: 3**

---

## 🔴 Priority 1 (Critical) - Execute First

No P1 items pending.

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] Remove explicit any usage in auth callback and portfolio backup tests

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Replace explicit `any` usage with type-safe alternatives and keep error handling consistent.
**Files to Modify**: `frontend/src/pages/AuthCallbackPage.tsx`, `frontend/test/portfolioBackupValidation.test.ts`

#### Instructions:

1. Open `frontend/src/pages/AuthCallbackPage.tsx` and replace its contents with the code below
2. Open `frontend/test/portfolioBackupValidation.test.ts` and replace its contents with the code below

#### Implementation Code:

```tsx
import React, { useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useSettings } from '../../hooks/SettingsContext';

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

            // URL에서 code와 state 추출
            const code = searchParams.get('code');
            const state = searchParams.get('state');
            const error = searchParams.get('error');
            const errorDescription = searchParams.get('error_description');

            // 에러 처리
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
                // 백엔드로 code와 state 전송하여 쿠키 기반 로그인 처리
                const response = await fetch(
                    `${settings.serverUrl}/api/auth/naver/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`,
                    { credentials: 'include' }
                );

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || '로그인 처리 중 오류가 발생했습니다.');
                }

                const data = await response.json();
                if (!data?.access_token) {
                    throw new Error('로그인 토큰을 받지 못했습니다. 다시 로그인해주세요.');
                }

                // 쿠키 기반 인증 상태 및 사용자 정보 저장
                setSettings((prev) => ({
                    ...prev,
                    cookieAuth: true,
                    naverUser: data.user,
                }));

                setStatus('success');

                // 1초 후 메인 페이지로 리다이렉트
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

        handleCallback();
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

    // error 상태
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

const asSnapshot = (value: Record<string, unknown>) => value as unknown as ImportedAssetSnapshot;

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

  it('normalizes ticker and infers currency when missing/invalid', () => {
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
- Expected: All frontend tests pass without TypeScript or lint errors

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

### [PROMPT-002] Clean up ESLint no-undef config and remove file-level disables

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Disable `no-undef` for TypeScript files and remove file-level disable comments.
**Files to Modify**: `eslint.config.js`, `frontend/src/shared/api/client/core.ts`, `frontend/src/shared/api/client/client.ts`, `frontend/test/apiClient.test.ts`

#### Instructions:

1. Open `eslint.config.js` and replace its contents with the code below
2. Open `frontend/src/shared/api/client/core.ts` and replace its contents with the code below
3. Open `frontend/src/shared/api/client/client.ts` and replace its contents with the code below
4. Open `frontend/test/apiClient.test.ts` and replace its contents with the code below

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
import {
    fetchMemories,
    getMemory,
    createMemory,
    updateMemory,
    deleteMemory,
    searchMemories,
    cleanupExpiredMemories,
    chatWithMemories,
} from './memories';
import {
    MemoryResponse,
    MemoryCreate,
    MemoryUpdate,
    MemorySearchRequest,
    MemoryCategory,
} from './types';

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

        // 레거시 API 토큰 (쿠키 인증이 없을 때만 사용)
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

    // --- Memories ---

    async fetchMemories(params: {
        category?: MemoryCategory;
        min_importance?: number;
        include_expired?: boolean;
        limit?: number;
        offset?: number;
    } = {}): Promise<MemoryResponse[]> {
        return fetchMemories(this.requestFn, params);
    }

    async getMemory(id: number): Promise<MemoryResponse> {
        return getMemory(this.requestFn, id);
    }

    async createMemory(payload: MemoryCreate): Promise<MemoryResponse> {
        return createMemory(this.requestFn, payload);
    }

    async updateMemory(id: number, payload: MemoryUpdate): Promise<MemoryResponse> {
        return updateMemory(this.requestFn, id, payload);
    }

    async deleteMemory(id: number): Promise<void> {
        return deleteMemory(this.requestFn, id);
    }

    async searchMemories(params: MemorySearchRequest): Promise<MemoryResponse[]> {
        return searchMemories(this.requestFn, params);
    }

    async cleanupExpiredMemories(): Promise<void> {
        return cleanupExpiredMemories(this.requestFn);
    }

    async *chatWithMemories(params: {
        messages: { role: string; content: string }[];
        model?: string;
        session_id?: string;
    }): AsyncGenerator<string> {
        yield* chatWithMemories(
            params,
            this.baseUrl,
            (withJson) => this.createHeaders(withJson)
        );
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
- Run: `npm run test --prefix frontend`
- Expected: Frontend tests pass and ESLint no-undef rule no longer requires file-level disables

**✅ After completing this prompt, proceed to [PROMPT-003]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-003] Add limit parameter support to news search API

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add a `limit` query parameter to `/api/news/search` and propagate it through the service layer.
**Files to Modify**: `backend/routers/news.py`, `backend/services/news_service.py`

#### Instructions:

1. Open `backend/routers/news.py` and replace its contents with the code below
2. Open `backend/services/news_service.py` and replace its contents with the code below

#### Implementation Code:

```py
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from ..core.db import get_db
from ..core.auth import verify_api_token
from ..core.rate_limit import rate_limit
from ..services import news_service

router = APIRouter(
    prefix="/api/news",
    tags=["News"],
    dependencies=[
        Depends(verify_api_token),
        Depends(rate_limit(limit=30, window_sec=60, key_prefix="news")),
    ],
)

@router.get("/search")
async def search_news(
    query: str = Query(..., description="검색어 (종목명, 게임명 등)"),
    ticker: Optional[str] = Query(None, description="티커 또는 종목코드"),
    category: Optional[str] = Query(None, description="카테고리 (economy, esports 등)"),
    limit: int = Query(15, ge=1, le=50, description="반환할 최대 기사 수"),
    db: Session = Depends(get_db)
):
    """
    관련 뉴스를 검색한다. 실시간 수집을 먼저 수행하여 최신성을 확보한다.
    비즈니스 로직은 news_service에서 처리한다.
    """
    return await news_service.search_news_logic(
        db=db,
        query=query,
        ticker=ticker,
        category=category,
        limit=limit
    )
```

```py
from __future__ import annotations

import logging
import re
from typing import List, Optional, Dict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.models_misc import GameNews
from .news.naver import collect_naver_news
from .news.google import collect_stock_news_google

logger = logging.getLogger(__name__)

def clean_asset_name(name: str) -> str:
    """종목명에서 불필요한 수식어나 브랜드명을 제거하여 검색 성능을 높인다."""
    # ETF 관련 수식어 및 해외 기업 접미사 제거 (단어 경계 \b 추가로 오탐 방지 - 도라 제안 💖)
    noise_keywords = [
        'ACE', 'KODEX', 'TIGER', 'RISE', 'SOL', 'HANARO', 'KBSTAR', 'PLUS', 
        'Ultra', 'ProShares', 'ETF', 'Plus', 'Ltd', 'Inc', 'Corp', 'Group', 'Holding'
    ]
    pattern = r'\b(' + '|'.join(noise_keywords) + r')\b'
    name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    
    # 괄호 및 특수문자 제거
    name = re.sub(r'[\(\)\[\]]', ' ', name)
    # 불필요한 공백 정리
    name = " ".join(name.split()).strip()
    return name

def extract_market_keywords(name: str) -> List[str]:
    """종목명에서 시장 지수나 핵심 산업 키워드를 추출한다."""
    keywords = []
    # 주요 지수 패턴
    indices = ["S&P500", "나스닥100", "NASDAQ100", "코스피200", "KOSPI200", "반도체", "2차전지", "전기차", "빅테크"]
    for idx in indices:
        if idx.lower() in name.lower():
            keywords.append(idx)
    return keywords

def is_foreign_stock(ticker: str, query: str, db: Optional[Session] = None) -> bool:
    """
    해외 종목인지 판별한다. (도라 & 비키 제안 반영 💖)
    1. DB의 market_type 정보 최우선 참조
    2. 티커 패턴 및 거래소 접두사 분석
    """
    if db and ticker:
        from ..core.models import Asset
        asset = db.query(Asset).filter(Asset.ticker == ticker).first()
        if asset and asset.market_type:
            if asset.market_type.upper() in ["KRX", "KOSPI", "KOSDAQ"]:
                return False
            if asset.market_type.upper() in ["NASDAQ", "NYSE", "AMEX", "GLOBAL"]:
                return True

    if not ticker:
        return False
    
    # 티커에서 거래소 접두사 제거 (NAS:NVDA -> NVDA)
    clean_ticker = ticker.split(":")[-1] if ":" in ticker else ticker
    exchange_prefix = ticker.split(":")[0].upper() if ":" in ticker else ""
    
    # 거래소 접두사로 직관적 판별
    if exchange_prefix in ["NAS", "NASDAQ", "NYSE", "AMEX"]:
        return True
    
    # 숫자 포함 티커는 국내 종목 (005930 등)
    if any(c.isdigit() for c in clean_ticker):
        return False
    
    # 순수 영문 티커인지 확인
    if not clean_ticker.isalpha():
        return False
    
    # 국내 ETF 브랜드 키워드 체크 (부분 매칭 방지를 위해 정확한 브랜드 목록 사용)
    domestic_etf_brands = ["KODEX", "TIGER", "ACE", "RISE", "SOL", "HANARO", "KBSTAR", "PLUS"]
    query_upper = query.upper() if query else ""
    if any(brand in query_upper for brand in domestic_etf_brands):
        return False
    
    # 영문 티커면서 길이 조건 만족 시 해외
    return len(clean_ticker) >= 2

async def search_news_logic(
    db: Session,
    query: str,
    ticker: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 15,
) -> Dict:
    """
    관련 뉴스를 검색하고 실시간 수집을 수행하는 핵심 비즈니스 로직.
    """
    cleaned_query = clean_asset_name(query)
    market_keywords = extract_market_keywords(query)
    
    # 카테고리 추론
    is_economy = category == "economy" or ticker is not None or len(market_keywords) > 0

    limit = max(1, min(int(limit), 50))
    db_limit = max(limit * 2, 30)
    
    # 티커 전처리
    clean_ticker = ticker
    if ticker and ":" in ticker:
        clean_ticker = ticker.split(":")[-1]
    
    # 실시간 검색어 후보군 생성
    realtime_search_terms = []
    if market_keywords:
        realtime_search_terms.append(market_keywords[0])
    
    if clean_ticker and clean_ticker.isalpha():
        if cleaned_query:
            realtime_search_terms.append(cleaned_query)
            realtime_search_terms.append(f"{cleaned_query} 주가")
            realtime_search_terms.append(f"{cleaned_query} {clean_ticker}")
        else:
            realtime_search_terms.append(clean_ticker)
    else:
        combined_term = f"{cleaned_query} {clean_ticker}" if clean_ticker else cleaned_query
        realtime_search_terms.append(combined_term)
    
    is_foreign = is_foreign_stock(ticker, query, db=db)
    
    # 1. 실시간 수집 수행
    try:
        collect_cat = "economy" if is_economy else "esports"
        if is_foreign:
            logger.info(f"Using Google News for foreign stock: ticker='{clean_ticker}', query='{cleaned_query}'")
            await collect_stock_news_google(db, clean_ticker, cleaned_query)
        else:
            for term in list(dict.fromkeys(realtime_search_terms))[:3]:
                logger.info(f"Triggering real-time collect for '{term}' (cat: {collect_cat})")
                await collect_naver_news(db, term, category=collect_cat)
    except Exception as e:
        logger.error(f"Error during real-time news collection: {e}")

    # 2. DB 검색
    filters = []
    search_tickers = [t for t in [clean_ticker, ticker] if t]
    for t in search_tickers:
        filters.append(GameNews.title.ilike(f"%{t}%"))
        filters.append(GameNews.full_content.ilike(f"%{t}%"))
        filters.append(GameNews.title.ilike(f"({t})"))
    
    for kw in market_keywords:
        filters.append(GameNews.title.ilike(f"%{kw}%"))
        
    if cleaned_query.upper() in ["LCK", "LPL", "LEC", "LCS", "VCT", "MSI", "WORLDS"]:
        filters.append(GameNews.league_tag == cleaned_query.upper())

    if cleaned_query and len(cleaned_query) >= 2:
        filters.append(GameNews.title.ilike(f"%{cleaned_query}%"))
        filters.append(GameNews.full_content.ilike(f"%{cleaned_query}%"))
        
    if not filters:
        articles = []
    else:
        query_obj = db.query(GameNews).filter(or_(*filters))
        if is_economy:
            query_obj = query_obj.filter(GameNews.source_name != "Steam")
            query_obj = query_obj.filter(GameNews.game_tag == "Economy")
            
        articles = query_obj.order_by(
            GameNews.event_time.desc().nulls_last(),
            GameNews.published_at.desc(), 
            GameNews.created_at.desc()
        ).limit(db_limit).all()

    # 3. 노이즈 필터링
    ticker_volume_pattern = re.compile(f"{ticker}\\s*(주|건|매|원|달러|%|\\+|-)") if ticker and ticker.isdigit() else None
    product_noise_pattern = re.compile(r"(보수\s*전쟁|보수\s*인하|순자산\s*돌파|운용보수|총보수|배당금\s*지급|일정\s*변경|일반사무관리)")
    foreign_lang_pattern = re.compile(r"^[A-Za-zÀ-ÿ\s,.'\"!?¿¡-]+$")
    unrelated_industry_pattern = re.compile(r"(Lunsumio|룬수미오|피하주사|경쟁서|로슈|Roche|Eli Lilly|FDA|임상\s*[1-3]상|신약\s*허가)", re.IGNORECASE)
    
    filtered_articles = []
    for art in articles:
        if ticker_volume_pattern and (ticker_volume_pattern.search(art.title) or ticker_volume_pattern.search(art.full_content)):
            continue
        if market_keywords and product_noise_pattern.search(art.title):
            continue
        has_summary = hasattr(art, 'summary') and art.summary
        if not has_summary and foreign_lang_pattern.match(art.title.strip()):
            continue
        if unrelated_industry_pattern.search(art.title) or unrelated_industry_pattern.search(art.full_content or ""):
            continue
        filtered_articles.append(art)
    
    articles = filtered_articles[:limit]
    
    result = []
    for art in articles:
        result.append({
            "id": art.id,
            "title": art.title,
            "url": art.url,
            "source_name": art.source_name,
            "published_at": art.published_at.isoformat() if art.published_at else None,
            "snippet": art.full_content[:150] + "..." if art.full_content and len(art.full_content) > 150 else (art.full_content or ""),
            "summary": art.summary if hasattr(art, 'summary') else None
        })
        
    return {
        "query": query,
        "ticker": ticker,
        "category": category,
        "count": len(result),
        "articles": result
    }
```

#### Verification:
- Run: `python -m unittest discover backend/tests`
- Expected: All backend tests pass

**✅ After completing this prompt, proceed to [PROMPT-003]**

**🎉 ALL PROMPTS COMPLETED!**
