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
| 1 | PROMPT-001 | [P2-1] Implement API Client Unit Tests | P2 | ⬜ Pending |
| 2 | PROMPT-002 | [P3-1] Implement Expense Statistics Chart | P3 | ⬜ Pending |

**Total: 2 prompts** | **Completed: 0** | **Remaining: 2**

---

## 🔴 Priority 1 (Critical) - Execute First

*(None - P1 tasks are clear)*

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] Implement API Client Unit Tests

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Create a unit test file for `lib/api/client.ts` to ensure API methods are correctly formatted and calls are mocked.
**Files to Modify**: `/home/dlckdgn/personal-portfolio/test/api.test.ts` (Create New)

#### Instructions:

1.  **Create `test/api.test.ts`**: Implement unit tests using `vitest`.
2.  **Mock Logic**: Use `vi.spyOn(global, 'fetch')` to mock successful and failed API responses.
3.  **Test Cases**:
    -   `fetchHealth`: Should return health check response.
    -   `fetchPortfolio`: Should return portfolio data.
    -   `fetchExpenses`: Should format query parameters correctly (year, month).
    -   `deleteExpense`: Should call DELETE method correctly.

#### Implementation Code:

```typescript
// /home/dlckdgn/personal-portfolio/test/api.test.ts

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ApiClient } from '../lib/api/client';
import type { BackendHealthResponse, BackendPortfolioResponse } from '../lib/api/types';

describe('ApiClient', () => {
    let client: ApiClient;
    const baseUrl = 'http://localhost:8000';
    const token = 'test-token';

    beforeEach(() => {
        client = new ApiClient(baseUrl, token);
        // Mock global fetch
        global.fetch = vi.fn();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('should initialize with correct base URL', () => {
        // Private property access for testing requires 'any' or explicit check via public methods if available
        // Here we test behavior invoking fetch
        expect(client).toBeDefined();
    });

    it('checkHealth calls /api/health', async () => {
        const mockResponse: BackendHealthResponse = { status: 'ok', version: '1.0' };
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => mockResponse,
        } as Response);

        const result = await client.checkHealth();
        
        expect(fetch).toHaveBeenCalledWith(`${baseUrl}/api/health`, expect.objectContaining({
            method: 'GET',
            headers: expect.objectContaining({ 'X-API-Token': token })
        }));
        expect(result).toEqual(mockResponse);
    });

    it('fetchPortfolio calls /api/portfolio', async () => {
        const mockData: BackendPortfolioResponse = { 
            summary: { total_value: 1000, total_invested: 900, total_profit: 100, profit_rate: 11.1, exchange_rate: 1300 },
            assets: [],
            composition: { by_asset_class: [], by_currency: [] }
        };
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => mockData,
        } as Response);

        const result = await client.fetchPortfolio();
        expect(result).toEqual(mockData);
        expect(fetch).toHaveBeenCalledWith(`${baseUrl}/api/portfolio`, expect.anything());
    });

    it('fetchExpenses constructs query params correctly', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            json: async () => [],
        } as Response);

        await client.fetchExpenses({ year: 2025, month: 1, category: 'Food' });

        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('year=2025'),
            expect.anything()
        );
        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('month=1'),
            expect.anything()
        );
        expect(fetch).toHaveBeenCalledWith(
            expect.stringContaining('category=Food'),
            expect.anything()
        );
    });

    it('deleteExpense calls DELETE method', async () => {
        vi.mocked(fetch).mockResolvedValueOnce({
            ok: true,
            status: 204, // No content
            text: async () => '',
        } as Response);

        await client.deleteExpense(123);

        expect(fetch).toHaveBeenCalledWith(
            `${baseUrl}/api/expenses/123`,
            expect.objectContaining({ method: 'DELETE' })
        );
    });
});
```

#### Verification:
- Run: `npm test test/api.test.ts` or `pnpm test test/api.test.ts`
- Expected: All tests passed.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-002] Implement Expense Statistics Chart

**⏱️ Execute this prompt now, then report completion.**

**Task**: Visualize expense data using Recharts (Pie Chart for Category Distribution).
**Files to Modify**: 
1. `/home/dlckdgn/personal-portfolio/lib/api/types.ts`
2. `/home/dlckdgn/personal-portfolio/lib/api/client.ts`
3. `/home/dlckdgn/personal-portfolio/components/ExpensesDashboard.tsx`

#### Instructions:

1.  **Update `lib/api/types.ts`**: Add `BackendExpenseSummary` interface.
2.  **Update `lib/api/client.ts`**: Add `fetchExpenseSummary` method to `ApiClient` class.
3.  **Update `ExpensesDashboard.tsx`**: Fetch usage and display Chart.

#### Implementation Code (Part 1 - lib/api/types.ts):

```typescript
// Append to the end of lib/api/types.ts

export interface BackendExpenseSummary {
    period: { year: number; month: number | null };
    total_expense: number;
    total_income: number;
    net: number;
    category_breakdown: { category: string; amount: number }[];
    method_breakdown: { method: string; amount: number }[];
}
```

#### Implementation Code (Part 2 - lib/api/client.ts):

```typescript
// Add inside ApiClient class, for example after fetchExpenses method

    async fetchExpenseSummary(params?: {
        year?: number;
        month?: number;
    }): Promise<BackendExpenseSummary> {
        const search = new URLSearchParams();
        if (params?.year != null) search.set('year', params.year.toString());
        if (params?.month != null) search.set('month', params.month.toString());
        return this.request<BackendExpenseSummary>(`/api/expenses/summary?${search.toString()}`, {
            method: 'GET',
        });
    }
```

#### Implementation Code (Part 3 - components/ExpensesDashboard.tsx):

```typescript
// Replace appropriate sections in ExpensesDashboard.tsx
// 1. Add Imports
import { PieChart, Pie, Cell, Tooltip as RechartsTooltip, Legend, ResponsiveContainer } from 'recharts';
import type { BackendExpenseSummary } from '../lib/api/types';

// 2. Add inside Component State
const [summary, setSummary] = useState<BackendExpenseSummary | null>(null);

// 3. Update loadExpenses function
const loadExpenses = useCallback(async (year: number, month: number) => {
    setIsLoading(true);
    setError(null);
    try {
        const [listData, summaryData] = await Promise.all([
            apiClient.fetchExpenses({ year, month }, { signal: controller.signal }),
            apiClient.fetchExpenseSummary({ year, month })
        ]);
        setExpenses(listData);
        setSummary(summaryData);
    } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') return;
        setError(getUserErrorMessage(err));
    } finally {
        setIsLoading(false);
    }
}, []);

// 4. Add Chart UI (Above the table)
const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6'];

// Render logic update:
// ... (inside return)
{summary && summary.category_breakdown.length > 0 && (
  <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 mb-6">
    <h3 className="text-lg font-semibold text-slate-900 mb-4">카테고리별 지출</h3>
    <div className="h-[300px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={summary.category_breakdown}
            dataKey="amount"
            nameKey="category"
            cx="50%"
            cy="50%"
            outerRadius={100}
            fill="#8884d8"
            label={({name, percent}) => `${name} ${(percent * 100).toFixed(0)}%`}
          >
            {summary.category_breakdown.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <RechartsTooltip formatter={(value: number) => new Intl.NumberFormat('ko-KR', { style: 'currency', currency: 'KRW' }).format(value)} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  </div>
)}
{/* Followed by existing Table code... */}
```

#### Verification:
- Run: `pnpm run compile` to check types.
- Check: Expense Dashboard shows a Pie Chart when data is loaded.

**🎉 ALL PROMPTS COMPLETED!**
