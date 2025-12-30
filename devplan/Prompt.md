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
| 1 | PROMPT-001 | Add API request timeouts and classify timeout errors | P2 | ⬜ Pending |
| 2 | PROMPT-002 | Export trade history to CSV | P3 | ⬜ Pending |

**Total: 2 prompts** | **Completed: 0** | **Remaining: 2**

---

## 🟡 Priority 2 (High) - Execute First

### [PROMPT-001] Add API request timeouts and classify timeout errors

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add request timeouts to ApiClient using AbortController and classify timeout errors so the UI can display better messages.  
**Files to Modify**: `backendClient.ts`, `errors.ts`

#### Instructions:

1. Open `backendClient.ts`
2. Add a `TimeoutError` class after the existing error classes
3. Add a default timeout constant (e.g., 15000ms)
4. Modify the `request` method to use AbortController with timeout
5. Update `errors.ts` to recognize `TimeoutError` and allow a `timeout` message in `alertError`

#### Implementation Code:

**File: `backendClient.ts`** - Add TimeoutError class after ApiError:

```typescript
export class TimeoutError extends Error {
  constructor(public readonly url: string, public readonly timeoutMs: number) {
    super(
      `API Request Timed Out: ${url}${timeoutMs > 0 ? ` (${timeoutMs}ms)` : ''}`,
    );
    this.name = 'TimeoutError';
  }
}
```

**File: `backendClient.ts`** - Add timeout constant and helper:

```typescript
const DEFAULT_TIMEOUT_MS = 15000;

const isAbortError = (error: unknown): boolean =>
  typeof error === 'object' &&
  error !== null &&
  'name' in error &&
  (error as { name?: string }).name === 'AbortError';
```

**File: `backendClient.ts`** - Update the `request` method to use AbortController:

The request method should:
1. Create an AbortController
2. Set a timeout using setTimeout to call controller.abort()
3. Pass controller.signal to fetch
4. In catch block, check if error is AbortError and throw TimeoutError
5. Clear timeout in finally block

**File: `errors.ts`** - Update alertError to handle TimeoutError:

```typescript
import { ApiError, NetworkError, TimeoutError } from './backendClient';

interface AlertMessages {
  default: string;
  unauthorized?: string;
  network?: string;
  timeout?: string;
}

export function alertError(
  context: string,
  error: unknown,
  messages: AlertMessages,
): void {
  console.error(`[${context}]`, error);

  if (error instanceof TimeoutError) {
    alert(messages.timeout ?? messages.default);
    return;
  }

  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) {
      alert(messages.unauthorized ?? messages.default);
    } else {
      alert(messages.default);
    }
    return;
  }

  if (error instanceof NetworkError) {
    alert(messages.network ?? messages.default);
    return;
  }

  alert(messages.default);
}
```

#### Verification:
- Run: `npm run typecheck`
- Expected: No TypeScript errors
- Test: Slow network should show timeout error message instead of hanging indefinitely

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-002] Export trade history to CSV

**⏱️ Execute this prompt now**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add a button to export the currently displayed trade history (with applied filters) as a CSV file.  
**Files to Modify**: `components/TradeHistoryAll.tsx`

#### Instructions:

1. Open `components/TradeHistoryAll.tsx`
2. Add a CSV export function that converts the filtered/displayed trades to CSV format
3. Add an export button in the header section next to the search/filter controls
4. The CSV should include columns: Date, Asset Name, Ticker, Type, Quantity, Price, Realized P/L

#### Implementation Code:

**Add this helper function inside the component:**

```typescript
const exportToCSV = () => {
  const headers = ['날짜', '자산명', '티커', '거래유형', '수량', '가격', '실현손익'];
  const rows = displayedTrades.map(trade => [
    new Date(trade.timestamp).toLocaleDateString('ko-KR'),
    trade.assetName,
    trade.ticker || '-',
    trade.type === 'BUY' ? '매수' : '매도',
    trade.quantity.toString(),
    trade.price.toLocaleString('ko-KR'),
    trade.realizedDelta?.toLocaleString('ko-KR') || '-',
  ]);
  
  const csvContent = [headers, ...rows]
    .map(row => row.map(cell => `"${cell}"`).join(','))
    .join('\n');
  
  const BOM = '\uFEFF';
  const blob = new Blob([BOM + csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `trade_history_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
};
```

**Add export button in the header/toolbar area:**

```tsx
import { Download } from 'lucide-react';

// In the component JSX, add button near filters:
<button
  onClick={exportToCSV}
  className="flex items-center gap-1.5 px-3 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors text-sm font-medium"
  title="CSV로 내보내기"
>
  <Download size={16} />
  CSV
</button>
```

#### Verification:
- Run: `npm run dev`
- Navigate to Trade History page
- Click CSV export button
- Expected: Downloads a CSV file with Korean headers and properly formatted data
- Verify: CSV opens correctly in Excel/Google Sheets with proper Korean encoding

**🎉 ALL PROMPTS COMPLETED! Run final verification:**
- `npm run typecheck` - No TypeScript errors
- `npm run dev` - Application runs correctly
- Test timeout behavior with slow network
- Test CSV export with filtered trade data
