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
| 1 | PROMPT-001 | [P2-1] Implement Expense Delete Functionality | P2 | ⬜ Pending |
| 2 | PROMPT-002 | [P3-1] Implement Expense Statistics Chart | P3 | ⬜ Pending |

**Total: 2 prompts** | **Completed: 0** | **Remaining: 2**

---

## 🔴 Priority 1 (Critical) - Execute First

*(None - P1 tasks are clear)*

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] Implement Expense Delete Functionality

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add `deleteExpense` method to the API client and implement the UI interactions (Delete button) in the Dashboard.
**Files to Modify**: 
1. `/home/dlckdgn/personal-portfolio/backendClient.ts`
2. `/home/dlckdgn/personal-portfolio/components/ExpensesDashboard.tsx`

#### Instructions:

1.  **Update `backendClient.ts`**: Add `deleteExpense` method to `ApiClient` class.
2.  **Update `ExpensesDashboard.tsx`**:
    -   Add `deleteExpense` handler to execute deletion (with confirmation alert).
    -   Add a "Delete" button to each row in the table (next to the Edit button).

#### Implementation Code (Part 1 - backendClient.ts):

```typescript
// Add this method to ApiClient class in backendClient.ts

  async deleteExpense(expenseId: number): Promise<void> {
    return this.request<void>(`/api/expenses/${expenseId}`, {
      method: 'DELETE',
    });
  }
```

#### Implementation Code (Part 2 - ExpensesDashboard.tsx):

*Modify `ExpensesDashboard` to include:*

1.  **Handler**:
    ```typescript
    const handleDelete = async (id: number) => {
      if (!window.confirm('정말 이 내역을 삭제하시겠습니까? 복구할 수 없습니다.')) return;
      if (!isRemoteEnabled) return;
      
      try {
        await apiClient.deleteExpense(id);
        // Optimistically remove from UI
        setExpenses(prev => prev.filter(e => e.id !== id));
      } catch (err) {
        alert(getUserErrorMessage(err, { default: '삭제 실패' }));
      }
    };
    ```

2.  **UI Addition (Delete Button)**:
    *In the table row action column:*
    ```typescript
    <button
      type="button"
      onClick={() => handleDelete(expense.id)}
      disabled={!isRemoteEnabled || savingId === expense.id}
      className="ml-2 px-3 py-1.5 rounded-lg text-xs font-medium text-rose-500 hover:text-rose-700 hover:bg-rose-50"
    >
      삭제
    </button>
    ```

#### Verification:
- Run: `pnpm run compile` (if available) or check for lint errors.
- Verify `deleteExpense` is correctly called.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-002] Implement Expense Statistics Chart

**⏱️ Execute this prompt now, then report completion.**

**Task**: Visualize expense data using Recharts (Pie Chart for Category Distribution).
**Files to Modify**: 
1. `/home/dlckdgn/personal-portfolio/backendClient.ts`
2. `/home/dlckdgn/personal-portfolio/components/ExpensesDashboard.tsx`

#### Instructions:

1.  **Update `backendClient.ts`**: Add `fetchExpenseSummary` method to `ApiClient`.
    *Ref: GET /api/expenses/summary?year=...&month=...*
2.  **Update `ExpensesDashboard.tsx`**:
    -   Fetch summary data when `selectedMonth` changes.
    -   Display a Recharts PieChart showing `category_breakdown`.

#### Implementation Code (Part 1 - backendClient.ts):

```typescript
// Add to backendClient.ts / ApiClient
export interface BackendExpenseSummary {
  period: { year: number; month: number | null };
  total_expense: number;
  total_income: number;
  net: number;
  category_breakdown: { category: string; amount: number }[];
  method_breakdown: { method: string; amount: number }[];
}

// Inside ApiClient class:
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

#### Implementation Code (Part 2 - ExpensesDashboard.tsx):

```typescript
// Add Imports
import { PieChart, Pie, Cell, Tooltip as RechartsTooltip, Legend, ResponsiveContainer } from 'recharts';
import { BackendExpenseSummary } from '../backendClient';

// Add State
const [summary, setSummary] = useState<BackendExpenseSummary | null>(null);

// Update Loader to fetch summary
const loadExpenses = useCallback(async (year: number, month: number) => {
    // ... existing logic ...
    try {
        const [listData, summaryData] = await Promise.all([
            apiClient.fetchExpenses({ year, month }, { signal: controller.signal }),
            apiClient.fetchExpenseSummary({ year, month })
        ]);
        setExpenses(listData);
        setSummary(summaryData);
    } catch (err) { ... }
    // ...
}, ...);

// Add Chart UI Component
const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6'];

// Render Chart Section above the list
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
          <RechartsTooltip formatter={(value: number) => formatCurrency(value)} />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  </div>
)}
```

#### Verification:
- Check that the chart renders and correct total amounts are shown.

**🎉 ALL PROMPTS COMPLETED!**
