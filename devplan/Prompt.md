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
| 1 | PROMPT-001 | API Client 유닛 테스트 보강 (API Client Unit Tests) | P2 | ⬜ Pending |
| 2 | PROMPT-002 | 스팸 규칙 API 인증 적용 (Secure Spam Rules API) | P2 | ⬜ Pending |
| 3 | PROMPT-003 | 지출 요약 차트 추가 (Expense Summary Charts) | P3 | ⬜ Pending |

**Total: 3 prompts** | **Completed: 0** | **Remaining: 3**

---

## 🔴 Priority 1 (Critical) - Execute First

*(None - P1 tasks are clear)*

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] API Client 유닛 테스트 보강 (API Client Unit Tests)

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add Vitest coverage for `ApiClient` request behaviors (success, query params, DELETE, and error handling).
**Files to Modify**: `/home/dlckdgn/personal-portfolio/frontend/test/apiClient.test.ts` (Create New)

#### Instructions:

1. Create the test file in `frontend/test`.
2. Mock `fetch` using `vi.stubGlobal`.
3. Assert request URLs, headers, and error handling.

#### Implementation Code:

```typescript
// /home/dlckdgn/personal-portfolio/frontend/test/apiClient.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient } from '../lib/api/client';
import { ApiError } from '../lib/api/errors';
import type { BackendHealthResponse, BackendPortfolioResponse } from '../lib/api/types';

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

    await client.fetchExpenses({ year: 2025, month: 1, category: '식비', includeDeleted: true });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain('/api/expenses?');
    expect(url).toContain('year=2025');
    expect(url).toContain('month=1');
    expect(url).toContain('category=%EC%8B%9D%EB%B9%84');
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
- Run: `npm run test --prefix frontend -- apiClient.test.ts`
- Expected: Tests pass.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

### [PROMPT-002] 스팸 규칙 API 인증 적용 (Secure Spam Rules API)

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Require API token authentication for `/api/spam-rules` and add backend tests to verify access control.
**Files to Modify**:
- `/home/dlckdgn/personal-portfolio/backend/routers/spam_rules.py`
- `/home/dlckdgn/personal-portfolio/backend/tests/test_spam_rules.py` (Create New)

#### Instructions:

1. Add `verify_api_token` as a dependency for the spam rules router.
2. Create tests that assert 401 without token and success with token.
3. Clean the `spam_rules` table before each test.

#### Implementation Code:

```python
# /home/dlckdgn/personal-portfolio/backend/routers/spam_rules.py
"""
Spam Rules Router - 스팸 규칙 CRUD API
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.auth import verify_api_token
from ..core.db import get_db
from ..core.models import SpamRule

router = APIRouter(
    prefix="/api/spam-rules",
    tags=["spam-rules"],
    dependencies=[Depends(verify_api_token)],
)


class SpamRuleCreate(BaseModel):
    rule_type: str  # 'contains' | 'regex' | 'promo_combo'
    pattern: str
    category: str = "general"
    note: Optional[str] = None


class SpamRuleResponse(BaseModel):
    id: int
    rule_type: str
    pattern: str
    category: str
    note: Optional[str]
    is_enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[SpamRuleResponse])
def list_spam_rules(db: Session = Depends(get_db)):
    """스팸 규칙 목록 조회"""
    return db.query(SpamRule).order_by(SpamRule.id).all()


@router.post("", response_model=SpamRuleResponse)
def create_spam_rule(rule: SpamRuleCreate, db: Session = Depends(get_db)):
    """스팸 규칙 추가"""
    new_rule = SpamRule(
        rule_type=rule.rule_type,
        pattern=rule.pattern,
        category=rule.category,
        note=rule.note,
        is_enabled=True,
        created_at=datetime.utcnow(),
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return new_rule


@router.delete("/{rule_id}")
def delete_spam_rule(rule_id: int, db: Session = Depends(get_db)):
    """스팸 규칙 삭제"""
    rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"message": f"Rule {rule_id} deleted"}


@router.patch("/{rule_id}/toggle")
def toggle_spam_rule(rule_id: int, db: Session = Depends(get_db)):
    """스팸 규칙 활성화/비활성화 토글"""
    rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_enabled = not rule.is_enabled
    db.commit()
    return {"id": rule_id, "is_enabled": rule.is_enabled}
```

```python
# /home/dlckdgn/personal-portfolio/backend/tests/test_spam_rules.py
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_temp_dir.name}/test.db")
os.environ["API_TOKEN"] = "test-token"

from backend.main import app  # noqa: E402
from backend.core.db import SessionLocal  # noqa: E402
from backend.core.models import SpamRule  # noqa: E402


class SpamRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.headers = {"X-API-Token": "test-token"}
        db = SessionLocal()
        try:
            db.query(SpamRule).delete()
            db.commit()
        finally:
            db.close()

    def test_requires_api_token(self) -> None:
        response = self.client.get("/api/spam-rules")
        self.assertEqual(response.status_code, 401)

    def test_create_and_list_rules(self) -> None:
        payload = {
            "rule_type": "contains",
            "pattern": "promo",
            "category": "general",
            "note": "test",
        }
        create_response = self.client.post(
            "/api/spam-rules",
            headers=self.headers,
            json=payload,
        )
        self.assertEqual(create_response.status_code, 200)
        created = create_response.json()
        self.assertEqual(created["pattern"], "promo")

        list_response = self.client.get("/api/spam-rules", headers=self.headers)
        self.assertEqual(list_response.status_code, 200)
        rules = list_response.json()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["pattern"], "promo")
```

#### Verification:
- Run: `python -m unittest backend/tests/test_spam_rules.py`
- Expected: Tests pass.

**✅ After completing this prompt, proceed to [PROMPT-003]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-003] 지출 요약 차트 추가 (Expense Summary Charts)

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Display expense summary charts and metrics using the existing `/api/expenses/summary` endpoint.
**Files to Modify**:
- `/home/dlckdgn/personal-portfolio/frontend/lib/api/types.ts`
- `/home/dlckdgn/personal-portfolio/frontend/lib/api/client.ts`
- `/home/dlckdgn/personal-portfolio/frontend/components/ExpensesDashboard.tsx`

#### Instructions:

1. Add `BackendExpenseSummary` to `types.ts`.
2. Add `fetchExpenseSummary` to `ApiClient`.
3. Fetch summary data and render a pie chart plus summary metrics in `ExpensesDashboard`.

#### Implementation Code:

```typescript
// /home/dlckdgn/personal-portfolio/frontend/lib/api/types.ts
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

export interface BackendExpenseSummary {
    period: { year: number | null; month: number | null };
    total_expense: number;
    total_income: number;
    net: number;
    fixed_expense: number;
    fixed_ratio: number;
    category_breakdown: { category: string; amount: number }[];
    method_breakdown: { method: string; amount: number }[];
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
```

```typescript
// /home/dlckdgn/personal-portfolio/frontend/lib/api/client.ts
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
    BackendExpenseSummary,
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

    async fetchExpenseSummary(params?: {
        year?: number;
        month?: number;
    }): Promise<BackendExpenseSummary> {
        const search = new URLSearchParams();
        if (params?.year != null) search.set('year', params.year.toString());
        if (params?.month != null) search.set('month', params.month.toString());
        const qs = search.toString();
        return this.request<BackendExpenseSummary>(`/api/expenses/summary${qs ? `?${qs}` : ''}`, {
            method: 'GET',
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
```

```typescript
// /home/dlckdgn/personal-portfolio/frontend/components/ExpensesDashboard.tsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { PieChart, Pie, Cell, Legend, ResponsiveContainer, Tooltip as RechartsTooltip } from 'recharts';
import { ApiClient, BackendExpense, BackendExpenseSummary, BackendExpenseUploadResult } from '../lib/api';
import { COLORS, formatCurrency } from '../lib/utils/constants';
import { getUserErrorMessage } from '../lib/utils/errors';
import { ExpenseRow, ExpenseUploadPanel } from './expenses';

interface ExpensesDashboardProps {
  serverUrl: string;
  apiToken?: string;
}

const COMMON_CATEGORIES = [
  '식비', '교통', '주거/통신', '구독', '쇼핑', '의료/건강',
  '경조사/선물', '교육', '취미', '생활', '이체', '투자',
  '기타', '급여', '기타수입',
];

const getDefaultMonthValue = () => {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
};

const parseYearMonth = (value: string) => {
  const [yearPart, monthPart] = value.split('-');
  const year = Number(yearPart);
  const month = Number(monthPart);
  if (!Number.isFinite(year) || !Number.isFinite(month)) return null;
  return { year, month };
};

export const ExpensesDashboard: React.FC<ExpensesDashboardProps> = ({ serverUrl, apiToken }) => {
  const [uploadResult, setUploadResult] = useState<BackendExpenseUploadResult | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [expenses, setExpenses] = useState<BackendExpense[]>([]);
  const [summary, setSummary] = useState<BackendExpenseSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedMonth, setSelectedMonth] = useState(() => getDefaultMonthValue());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draftCategory, setDraftCategory] = useState('');
  const [draftAmount, setDraftAmount] = useState<number>(0);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savingId, setSavingId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [globalCategories, setGlobalCategories] = useState<string[]>([]);
  const [isCustomCategoryMode, setIsCustomCategoryMode] = useState(false);
  const [isLearning, setIsLearning] = useState(false);
  const [learnResult, setLearnResult] = useState<{ added: number; updated: number; ai_trained?: boolean } | null>(null);
  const [showDeleted, setShowDeleted] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const expensesAbortRef = useRef<AbortController | null>(null);
  const fallbackYearMonth = useMemo(() => ({ year: new Date().getFullYear(), month: new Date().getMonth() + 1 }), []);

  const isRemoteEnabled = Boolean(serverUrl && apiToken);
  const apiClient = useMemo(() => new ApiClient(serverUrl, apiToken), [serverUrl, apiToken]);
  const selectedYearMonth = useMemo(() => parseYearMonth(selectedMonth) ?? fallbackYearMonth, [fallbackYearMonth, selectedMonth]);
  const yearOptions = useMemo(() => Array.from({ length: 7 }, (_, i) => fallbackYearMonth.year - 5 + i), [fallbackYearMonth.year]);

  const dynamicCategories = useMemo(() => {
    const existing = new Set<string>(COMMON_CATEGORIES);
    globalCategories.forEach((c) => existing.add(c));
    expenses.forEach((e) => { if (e.category) existing.add(e.category); });
    return Array.from(existing).sort();
  }, [expenses, globalCategories]);

  const summaryCategories = useMemo(() => summary?.category_breakdown ?? [], [summary]);

  // 표시할 내역 필터링: showDeleted가 false면 삭제되지 않은 것만
  const displayedExpenses = useMemo(() => {
    if (showDeleted) return expenses;
    return expenses.filter((e) => e.deleted_at == null);
  }, [expenses, showDeleted]);

  // 통계는 삭제되지 않은 항목만으로 계산
  const activeExpenses = useMemo(() => expenses.filter((e) => e.deleted_at == null), [expenses]);

  const loadExpenses = useCallback(async (year: number, month: number) => {
    if (!isRemoteEnabled) return;
    if (expensesAbortRef.current) expensesAbortRef.current.abort();
    const controller = new AbortController();
    expensesAbortRef.current = controller;
    setIsLoading(true);
    setLoadError(null);
    setSaveError(null);
    setEditingId(null);
    setDraftCategory('');
    setSummary(null);
    try {
      // 항상 삭제된 항목도 포함해서 조회 (토글로 표시/숨김 처리)
      const [data, summaryData] = await Promise.all([
        apiClient.fetchExpenses({ year, month, includeDeleted: true }, { signal: controller.signal }),
        apiClient.fetchExpenseSummary({ year, month }),
      ]);
      setExpenses(data);
      setSummary(summaryData);
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') return;
      setLoadError(getUserErrorMessage(err, { default: '가계부 내역을 불러오는 중 문제가 발생했습니다.' }));
    } finally {
      if (expensesAbortRef.current === controller) setIsLoading(false);
    }
  }, [apiClient, isRemoteEnabled]);

  const fetchGlobalCategories = useCallback(async () => {
    if (!isRemoteEnabled) return;
    try {
      const cats = await apiClient.fetchCategories();
      setGlobalCategories(cats);
    } catch (err) {
      console.error('[ExpensesDashboard] Failed to fetch global categories:', err);
    }
  }, [apiClient, isRemoteEnabled]);

  useEffect(() => {
    if (!isRemoteEnabled) return;
    void loadExpenses(selectedYearMonth.year, selectedYearMonth.month);
    void fetchGlobalCategories();
  }, [isRemoteEnabled, loadExpenses, fetchGlobalCategories, selectedYearMonth]);

  useEffect(() => {
    setExpenses([]);
    setSummary(null);
    setGlobalCategories([]);
    setLoadError(null);
    setEditingId(null);
    setDraftCategory('');
    setSaveError(null);
    setUploadError(null);
    setUploadResult(null);
    if (expensesAbortRef.current) {
      expensesAbortRef.current.abort();
      expensesAbortRef.current = null;
    }
  }, [serverUrl, apiToken]);

  const handlePickFile = () => { if (isRemoteEnabled && !isUploading) fileInputRef.current?.click(); };

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (!selectedFile) return;
    const fileName = selectedFile.name.toLowerCase();
    if (!['.xlsx', '.xls', '.csv'].some((ext) => fileName.endsWith(ext))) {
      setUploadError('Excel(.xlsx/.xls) 또는 CSV(.csv) 파일만 업로드할 수 있습니다.');
      setUploadResult(null);
      event.target.value = '';
      return;
    }
    setIsUploading(true);
    setUploadError(null);
    setUploadResult(null);
    try {
      const res = await apiClient.uploadExpenseFile(selectedFile);
      setUploadResult(res);
      void fetchGlobalCategories();
      const parsed = parseYearMonth(selectedMonth);
      if (parsed) void loadExpenses(parsed.year, parsed.month);
    } catch (err) {
      setUploadError(getUserErrorMessage(err, { default: '가계부 내역 업로드에 실패했습니다.' }));
    } finally {
      setIsUploading(false);
      event.target.value = '';
    }
  };

  const startEdit = (expense: BackendExpense) => {
    setEditingId(expense.id);
    setDraftCategory(expense.category ?? '');
    setDraftAmount(expense.amount);
    setSaveError(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraftCategory('');
    setDraftAmount(0);
    setSaveError(null);
    setIsCustomCategoryMode(false);
  };

  const saveExpense = async (expenseId: number) => {
    if (!isRemoteEnabled || savingId === expenseId) return;
    const trimmedCategory = draftCategory.trim();
    if (!trimmedCategory) { setSaveError('카테고리를 입력해주세요.'); return; }
    const current = expenses.find((e) => e.id === expenseId);
    if (!current) return;
    if (current.category === trimmedCategory && current.amount === draftAmount) { cancelEdit(); return; }
    setSavingId(expenseId);
    setSaveError(null);
    try {
      const updated = await apiClient.updateExpense(expenseId, { category: trimmedCategory, amount: draftAmount });
      setExpenses((prev) => prev.map((e) => (e.id === expenseId ? { ...e, category: updated.category, amount: updated.amount } : e)));
      void fetchGlobalCategories();
      cancelEdit();
    } catch (err) {
      setSaveError(getUserErrorMessage(err, { default: '내역 수정에 실패했습니다.' }));
    } finally {
      setSavingId(null);
    }
  };

  const deleteExpense = async (expenseId: number) => {
    if (!isRemoteEnabled || deletingId === expenseId) return;
    setDeletingId(expenseId);
    setSaveError(null);
    try {
      const result = await apiClient.deleteExpense(expenseId);
      // 로컬 상태 업데이트
      setExpenses((prev) => prev.map((e) =>
        e.id === expenseId ? { ...e, deleted_at: result.deleted_at ?? new Date().toISOString() } : e
      ));
    } catch (err) {
      setSaveError(getUserErrorMessage(err, { default: '내역 삭제에 실패했습니다.' }));
    } finally {
      setDeletingId(null);
    }
  };

  const restoreExpense = async (expenseId: number) => {
    if (!isRemoteEnabled || restoringId === expenseId) return;
    setRestoringId(expenseId);
    setSaveError(null);
    try {
      await apiClient.restoreExpense(expenseId);
      // 로컬 상태 업데이트
      setExpenses((prev) => prev.map((e) =>
        e.id === expenseId ? { ...e, deleted_at: null } : e
      ));
    } catch (err) {
      setSaveError(getUserErrorMessage(err, { default: '내역 복구에 실패했습니다.' }));
    } finally {
      setRestoringId(null);
    }
  };

  const handleLearn = async () => {
    if (!isRemoteEnabled || isLearning) return;
    setIsLearning(true);
    setLearnResult(null);
    try {
      const res = await apiClient.triggerLearning();
      setLearnResult(res);
      void fetchGlobalCategories();
      const parsed = parseYearMonth(selectedMonth);
      if (parsed) void loadExpenses(parsed.year, parsed.month);
    } catch (err) {
      console.error('[ExpensesDashboard] Failed to trigger learning:', err);
    } finally {
      setIsLearning(false);
    }
  };

  return (
    <section className="space-y-6">
      <ExpenseUploadPanel
        isRemoteEnabled={isRemoteEnabled}
        isUploading={isUploading}
        isLearning={isLearning}
        uploadError={uploadError}
        uploadResult={uploadResult}
        learnResult={learnResult}
        onPickFile={handlePickFile}
        onFileChange={handleFileChange}
        onLearn={handleLearn}
        onDismissLearnResult={() => setLearnResult(null)}
        fileInputRef={fileInputRef}
      />

      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">카테고리 수정</h2>
            <p className="text-sm text-slate-500 mt-1">자동 분류가 어긋난 항목만 직접 수정하세요.</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-500">조회 월</label>
              <div className="grid grid-cols-2 gap-2">
                <select value={selectedYearMonth.year} onChange={(e) => setSelectedMonth(`${Number(e.target.value)}-${String(selectedYearMonth.month).padStart(2, '0')}`)} disabled={!isRemoteEnabled} className="px-3 py-2 rounded-lg border border-slate-200 text-sm">
                  {yearOptions.map((y) => <option key={y} value={y}>{y}년</option>)}
                </select>
                <select value={selectedYearMonth.month} onChange={(e) => setSelectedMonth(`${selectedYearMonth.year}-${String(Number(e.target.value)).padStart(2, '0')}`)} disabled={!isRemoteEnabled} className="px-3 py-2 rounded-lg border border-slate-200 text-sm">
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}월</option>)}
                </select>
              </div>
            </div>
            {activeExpenses.length > 0 && (
              <div className="flex items-center gap-3 text-sm">
                <div className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 rounded-lg">
                  <span className="text-rose-500 text-xs">지출</span>
                  <span className="font-semibold text-rose-600 tabular-nums">{formatCurrency(Math.abs(activeExpenses.filter((e) => e.amount < 0).reduce((s, e) => s + e.amount, 0)))}</span>
                </div>
                <div className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-50 rounded-lg">
                  <span className="text-emerald-500 text-xs">수입</span>
                  <span className="font-semibold text-emerald-600 tabular-nums">{formatCurrency(activeExpenses.filter((e) => e.amount > 0).reduce((s, e) => s + e.amount, 0))}</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 삭제된 내역 보기 토글 */}
        <div className="mt-4 flex items-center gap-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={showDeleted}
              onChange={(e) => setShowDeleted(e.target.checked)}
              className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
            />
            <span className="text-sm text-slate-600">삭제된 내역 보기</span>
          </label>
          {showDeleted && expenses.filter((e) => e.deleted_at != null).length > 0 && (
            <span className="text-xs text-slate-400">
              ({expenses.filter((e) => e.deleted_at != null).length}건 삭제됨)
            </span>
          )}
        </div>

        {summary && summaryCategories.length > 0 && (
          <div className="mt-6 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="bg-slate-50 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-slate-700">카테고리 비중</h3>
                <span className="text-xs text-slate-400">총 {summary.transaction_count}건</span>
              </div>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={summaryCategories}
                      dataKey="amount"
                      nameKey="category"
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
                      labelLine={false}
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    >
                      {summaryCategories.map((entry, index) => (
                        <Cell key={`cell-${entry.category}-${index}`} fill={COLORS[index % COLORS.length]} />
                      ))}
                    </Pie>
                    <RechartsTooltip formatter={(value) => formatCurrency(Number(value))} />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="bg-slate-50 rounded-xl p-4">
              <h3 className="text-sm font-semibold text-slate-700 mb-3">요약 지표</h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">총 지출</span>
                  <span className="font-semibold text-rose-600 tabular-nums">{formatCurrency(summary.total_expense)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">총 수입</span>
                  <span className="font-semibold text-emerald-600 tabular-nums">{formatCurrency(summary.total_income)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">순수입</span>
                  <span className={`font-semibold tabular-nums ${summary.net >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                    {formatCurrency(summary.net)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">고정지출</span>
                  <span className="font-semibold text-slate-700 tabular-nums">{formatCurrency(summary.fixed_expense)}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">고정지출 비중</span>
                  <span className="font-semibold text-slate-700 tabular-nums">{summary.fixed_ratio.toFixed(1)}%</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {!isRemoteEnabled && <div className="mt-4 text-sm text-slate-500">서버 URL과 API 비밀번호를 먼저 설정해주세요.</div>}
        {loadError && <div className="mt-4 bg-red-50 text-red-600 p-3 rounded-lg text-sm flex items-start gap-2"><AlertCircle size={18} className="shrink-0 mt-0.5" /><span>{loadError}</span></div>}
        {saveError && <div className="mt-4 bg-amber-50 text-amber-700 p-3 rounded-lg text-sm flex items-start gap-2"><AlertCircle size={18} className="shrink-0 mt-0.5" /><span>{saveError}</span></div>}
        {isLoading && <div className="mt-4 flex items-center gap-2 text-sm text-slate-500"><Loader2 size={16} className="animate-spin" />불러오는 중...</div>}

        {!isLoading && displayedExpenses.length === 0 && !loadError && (
          <div className="mt-6 text-center">
            <div className="text-sm text-slate-400 mb-2">선택한 기간에 표시할 내역이 없습니다.</div>
            <div className="text-xs text-slate-500">상단의 <strong>내역 업로드</strong> 버튼을 눌러 가계부 데이터를 추가해주세요.</div>
          </div>
        )}

        {displayedExpenses.length > 0 && (
          <div className="mt-4 overflow-auto">
            <table className="w-full text-left border-collapse min-w-[720px]">
              <thead className="bg-slate-50 sticky top-0 z-10">
                <tr>
                  <th className="p-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">날짜</th>
                  <th className="p-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">가맹점</th>
                  <th className="p-3 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">금액</th>
                  <th className="p-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">카테고리</th>
                  <th className="p-3 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">편집</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {displayedExpenses.map((expense) => (
                  <ExpenseRow
                    key={expense.id}
                    expense={expense}
                    isEditing={editingId === expense.id}
                    draftCategory={draftCategory}
                    draftAmount={draftAmount}
                    dynamicCategories={dynamicCategories}
                    isCustomCategoryMode={isCustomCategoryMode}
                    isSaving={savingId === expense.id}
                    isDeleting={deletingId === expense.id}
                    isRestoring={restoringId === expense.id}
                    onEdit={startEdit}
                    onSave={(id) => void saveExpense(id)}
                    onCancel={cancelEdit}
                    onDelete={(id) => void deleteExpense(id)}
                    onRestore={(id) => void restoreExpense(id)}
                    onDraftCategoryChange={setDraftCategory}
                    onDraftAmountToggle={() => setDraftAmount((prev) => -prev)}
                    onCustomModeToggle={setIsCustomCategoryMode}
                    isRemoteEnabled={isRemoteEnabled}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
};
```

#### Verification:
- Run: `npm run typecheck --prefix frontend`
- Expected: No TypeScript errors and charts render with data.

**✅ After completing this prompt, proceed to [PROMPT-003]**

**🎉 ALL PROMPTS COMPLETED!**
