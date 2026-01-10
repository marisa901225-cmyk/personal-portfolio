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
| 1 | PROMPT-001 | Include Steam Trends in Game Trend RAG | P2 | ⬜ Pending |
| 2 | PROMPT-002 | Expense Summary Charts | P3 | ⬜ Pending |

**Total: 2 prompts** | **Completed: 0** | **Remaining: 2**

---

## 🔴 Priority 1 (Critical) - Execute First

*(None)*

---

## 🟡 Priority 2 (High) - Execute Second

### [PROMPT-001] Include Steam Trends in Game Trend RAG

**⏱️ Execute this prompt now, then proceed to PROMPT-002**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Fix Telegram `game_trend` answers by ensuring the RAG context includes SteamStore trends (`source_type='trend'`) and SteamSpy rankings.
**Files to Modify**:
- `/home/dlckdgn/personal-portfolio/backend/services/news/refiner.py`
- `/home/dlckdgn/personal-portfolio/backend/services/news/collector.py`
- `/home/dlckdgn/personal-portfolio/backend/routers/telegram_webhook.py`

#### Instructions:

1. Add a DuckDB refiner function that returns a compact Steam trends/rankings context.
2. Expose it via `NewsCollector`.
3. Update the Telegram `game_trend` branch to use the new refiner.

#### Implementation Code:

```python
# /home/dlckdgn/personal-portfolio/backend/services/news/refiner.py
# Add this function at the end of the file (below existing refine_* functions).

def refine_game_trends_with_duckdb(query_text: str, limit: int = 15) -> str:
    """
    DuckDB를 사용하여 Steam 트렌드/랭킹 데이터를 검색하고 고밀도 텍스트로 정제한다.
    - SteamStore: source_type='trend'
    - SteamSpy: source_name='SteamSpy' (source_type='news')
    """
    logger.info(f"Refining Steam game trends using DuckDB for query: {query_text}")
    try:
        db_path = get_db_path()
        con = duckdb.connect(":memory:")
        escaped_path = db_path.replace("'", "''")
        con.execute(f"ATTACH '{escaped_path}' AS sqlite_db (TYPE SQLITE, READ_ONLY)")

        q = (query_text or "").lower()
        where_clauses = [
            "(source_name IN ('SteamStore', 'SteamSpy') OR game_tag = 'Steam')"
        ]

        # 간단한 의도 분기: 신작/트렌드는 trend 위주, 랭킹/인기는 SteamSpy 위주
        if any(k in q for k in ["신작", "new", "출시", "release"]):
            where_clauses.append("source_type = 'trend'")
        elif any(k in q for k in ["랭킹", "순위", "top", "인기", "popular", "best"]):
            where_clauses.append("source_name = 'SteamSpy'")

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT
                strftime(published_at, '%m/%d %H:%M') as time,
                source_name,
                source_type,
                title,
                url,
                full_content
            FROM sqlite_db.game_news
            WHERE {where_sql}
            ORDER BY published_at DESC
            LIMIT {limit}
        """

        results = con.execute(sql).fetchall()
        if not results:
            return "수집된 Steam 트렌드/랭킹 데이터가 없습니다. 스케줄러가 실행되면 데이터가 쌓입니다."

        refined_items = []
        for r in results:
            time_str, _source_name, source_type, title, url, content = r
            icon = "🔥" if source_type == "trend" else "🏆"
            compact = (content or "").replace("\n", " ").strip()
            if len(compact) > 160:
                compact = compact[:160] + "…"

            line = f"{icon} {time_str} | {title}"
            if compact:
                line += f"\n   {compact}"
            if url:
                line += f"\n   🔗 {url}"
            refined_items.append(line)

        return "\n".join(refined_items)

    except Exception as e:
        logger.error(f"Failed to refine Steam game trends: {e}")
        return "게임 트렌드 정제 중 오류가 발생했습니다."
    finally:
        if 'con' in locals():
            con.close()
```

```python
# /home/dlckdgn/personal-portfolio/backend/services/news/collector.py
# Replace the entire file content with the following.

import logging
from .core import calculate_simhash, calculate_importance_score, RSS_FEEDS, NAVER_ESPORTS_QUERIES, NAVER_ECONOMY_QUERIES, GOOGLE_NEWS_MACRO_QUERIES
from .rss import collect_rss, collect_google_news, collect_all_google_news
from .naver import collect_naver_news, collect_all_naver_news
from .steam import collect_steamspy_rankings, collect_steam_new_trends
from .esports import collect_pandascore_schedules
from .refiner import refine_schedules_with_duckdb, refine_news_with_duckdb, refine_economy_news_with_duckdb, refine_game_trends_with_duckdb

logger = logging.getLogger(__name__)

class NewsCollector:
    """
    게임 뉴스 수집 및 전처리 Facade (Refactored)
    """

    RSS_FEEDS = RSS_FEEDS
    NAVER_ESPORTS_QUERIES = NAVER_ESPORTS_QUERIES
    NAVER_ECONOMY_QUERIES = NAVER_ECONOMY_QUERIES
    GOOGLE_NEWS_MACRO_QUERIES = GOOGLE_NEWS_MACRO_QUERIES

    @staticmethod
    def calculate_simhash(text: str) -> str:
        return calculate_simhash(text)

    @staticmethod
    def calculate_importance_score(title: str, source: str, published_at) -> int:
        return calculate_importance_score(title, source, published_at)

    @staticmethod
    def collect_rss(db, feed_url: str, source_name: str):
        return collect_rss(db, feed_url, source_name)

    @staticmethod
    async def collect_google_news(db, query: str, region: str = "US"):
        return await collect_google_news(db, query, region)

    @staticmethod
    async def collect_all_google_news(db):
        return await collect_all_google_news(db)

    @staticmethod
    async def collect_naver_news(db, query: str, category: str = "esports"):
        return await collect_naver_news(db, query, category)

    @staticmethod
    async def collect_all_naver_news(db):
        return await collect_all_naver_news(db)

    @staticmethod
    async def collect_steamspy_rankings(db):
        return await collect_steamspy_rankings(db)

    @staticmethod
    async def collect_steam_new_trends(db):
        return await collect_steam_new_trends(db)

    @staticmethod
    async def collect_pandascore_schedules(db):
        return await collect_pandascore_schedules(db)

    @staticmethod
    def refine_schedules_with_duckdb(query_text: str, limit: int = 15) -> str:
        return refine_schedules_with_duckdb(query_text, limit)

    @staticmethod
    def refine_news_with_duckdb(category: str = "economy", limit: int = 15) -> str:
        return refine_news_with_duckdb(category, limit)

    @staticmethod
    def refine_economy_news_with_duckdb(query_text: str, limit: int = 20) -> str:
        return refine_economy_news_with_duckdb(query_text, limit)

    @staticmethod
    def refine_game_trends_with_duckdb(query_text: str, limit: int = 15) -> str:
        return refine_game_trends_with_duckdb(query_text, limit)
```

```python
# /home/dlckdgn/personal-portfolio/backend/routers/telegram_webhook.py
# Replace only the `game_trend` branch with the following.

            # 3. 게임 트렌드 질의
            elif query_type == 'game_trend':
                from ..services.news_collector import NewsCollector
                context_text = NewsCollector.refine_game_trends_with_duckdb(text, limit=12)
                
                prompt = f"""<start_of_turn>user
당신은 게임 트렌드 전문가이자 사용자의 개인 비서입니다.
아래 제공된 최신 Steam 트렌드/랭킹 데이터를 바탕으로 사용자의 질문에 친절하게 답변해 주세요.

[최신 게임 트렌드 데이터]
{context_text}

[사용자의 질문]
{text}

[답변 규칙]
- 한국어로 답변하세요.
- 데이터에 있는 내용을 기반으로 정확하게 안내하세요.
- 게임 제목, 출시/인기 트렌드 포인트(가능하다면), 장르 등을 명확히 제시하세요.
- 친절하고 위트 있는 말투를 사용하세요.

답변:<end_of_turn>
<start_of_turn>model
"""
```

#### Verification:
- Run: `npm run test:backend`
- Expected: All backend tests pass.

**✅ After completing this prompt, proceed to [PROMPT-002]**

---

## 🟢 Priority 3 (Medium) - Execute Last

### [PROMPT-002] Expense Summary Charts

**⏱️ Execute this prompt now, then proceed to PROMPT-003**

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

**Task**: Add `/api/expenses/summary` support to the frontend and render a category pie chart + KPI summary in `ExpensesDashboard`.
**Files to Modify**:
- `/home/dlckdgn/personal-portfolio/frontend/lib/api/types.ts`
- `/home/dlckdgn/personal-portfolio/frontend/lib/api/client.ts`
- `/home/dlckdgn/personal-portfolio/frontend/components/ExpensesDashboard.tsx`
- `/home/dlckdgn/personal-portfolio/frontend/test/expensesDashboard.test.tsx`

#### Instructions:

1. Add a backend response type for expense summary.
2. Add `fetchExpenseSummary` to `ApiClient`.
3. Fetch the summary alongside the expenses list and render:
   - KPIs: total expense, total income, net, fixed ratio, transaction count
   - Pie chart: `category_breakdown`
4. Update the existing `ExpensesDashboard` test mock to include `fetchExpenseSummary`.

#### Implementation Code:

```typescript
// /home/dlckdgn/personal-portfolio/frontend/lib/api/types.ts
// Add the following definitions under the existing "Expenses" section (below BackendExpenseUploadResult).

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
```

```typescript
// /home/dlckdgn/personal-portfolio/frontend/lib/api/client.ts
// 1) Add `BackendExpenseSummaryResponse` to the imported types list.
// 2) Add the method below inside the existing `// --- Expenses ---` section.

async fetchExpenseSummary(
    params?: {
        year?: number;
        month?: number;
    },
    options: { signal?: AbortSignal } = {},
): Promise<BackendExpenseSummaryResponse> {
    const search = new URLSearchParams();
    if (params?.year != null) search.set('year', params.year.toString());
    if (params?.month != null) search.set('month', params.month.toString());
    const qs = search.toString();
    return this.request<BackendExpenseSummaryResponse>(`/api/expenses/summary${qs ? `?${qs}` : ''}`, {
        method: 'GET',
        signal: options.signal,
    });
}
```

```tsx
// /home/dlckdgn/personal-portfolio/frontend/components/ExpensesDashboard.tsx
// Replace the entire file content with the following.

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { ApiClient, BackendExpense, BackendExpenseSummaryResponse, BackendExpenseUploadResult } from '../lib/api';
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
  const [expenseSummary, setExpenseSummary] = useState<BackendExpenseSummaryResponse | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
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
    setSummaryError(null);
    setSaveError(null);
    setEditingId(null);
    setDraftCategory('');
    setExpenseSummary(null);
    try {
      // 항상 삭제된 항목도 포함해서 조회 (토글로 표시/숨김 처리)
      const data = await apiClient.fetchExpenses({ year, month, includeDeleted: true }, { signal: controller.signal });
      setExpenses(data);

      try {
        const summary = await apiClient.fetchExpenseSummary({ year, month }, { signal: controller.signal });
        setExpenseSummary(summary);
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') return;
        setSummaryError(getUserErrorMessage(err, { default: '지출 요약을 불러오는 중 문제가 발생했습니다.' }));
      }
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
    setExpenseSummary(null);
    setSummaryError(null);
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

  const fixedRatioText = useMemo(() => {
    if (!expenseSummary) return null;
    return `${expenseSummary.fixed_ratio.toFixed(1)}%`;
  }, [expenseSummary]);

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
                {fixedRatioText && (
                  <div className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-50 rounded-lg">
                    <span className="text-slate-500 text-xs">고정비</span>
                    <span className="font-semibold text-slate-700 tabular-nums">{fixedRatioText}</span>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {summaryError && (
          <div className="mt-4 bg-amber-50 text-amber-700 p-3 rounded-lg text-sm flex items-start gap-2">
            <AlertCircle size={18} className="shrink-0 mt-0.5" />
            <span>{summaryError}</span>
          </div>
        )}

        {expenseSummary && expenseSummary.category_breakdown.length > 0 && (
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-slate-50 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-slate-700">카테고리별 지출</h3>
                <div className="text-xs text-slate-500 tabular-nums">{expenseSummary.transaction_count}건</div>
              </div>
              <div className="mt-3 h-[240px] w-full">
                <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={240}>
                  <PieChart>
                    <Pie
                      data={expenseSummary.category_breakdown}
                      dataKey="amount"
                      nameKey="category"
                      cx="50%"
                      cy="50%"
                      innerRadius={70}
                      outerRadius={100}
                      paddingAngle={3}
                    >
                      {expenseSummary.category_breakdown.map((_, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="none" />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(value: number | string) => (typeof value === 'number' ? formatCurrency(value) : value)}
                      contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className="mt-4 space-y-1">
                {expenseSummary.category_breakdown.slice(0, 6).map((item, index) => (
                  <div key={item.category} className="flex items-center justify-between text-xs text-slate-600">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ background: COLORS[index % COLORS.length] }} />
                      <span className="truncate">{item.category}</span>
                    </div>
                    <span className="font-medium tabular-nums">{formatCurrency(item.amount)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-slate-50 rounded-xl p-4">
              <h3 className="text-sm font-semibold text-slate-700">요약 지표</h3>
              <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="bg-white rounded-lg border border-slate-100 p-3">
                  <div className="text-xs text-slate-500">순수입</div>
                  <div className="mt-1 font-semibold text-slate-900 tabular-nums">{formatCurrency(expenseSummary.net)}</div>
                </div>
                <div className="bg-white rounded-lg border border-slate-100 p-3">
                  <div className="text-xs text-slate-500">고정지출</div>
                  <div className="mt-1 font-semibold text-slate-900 tabular-nums">{formatCurrency(expenseSummary.fixed_expense)}</div>
                </div>
                <div className="bg-white rounded-lg border border-slate-100 p-3">
                  <div className="text-xs text-slate-500">고정비 비중</div>
                  <div className="mt-1 font-semibold text-slate-900 tabular-nums">{expenseSummary.fixed_ratio.toFixed(1)}%</div>
                </div>
                <div className="bg-white rounded-lg border border-slate-100 p-3">
                  <div className="text-xs text-slate-500">거래 건수</div>
                  <div className="mt-1 font-semibold text-slate-900 tabular-nums">{expenseSummary.transaction_count}건</div>
                </div>
              </div>
              <div className="mt-3 text-xs text-slate-500">
                * 차트/지표는 <strong>삭제되지 않은 항목</strong> 기준으로 계산됩니다.
              </div>
            </div>
          </div>
        )}

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

```tsx
// /home/dlckdgn/personal-portfolio/frontend/test/expensesDashboard.test.tsx
// Replace the entire file content with the following.

import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const fetchExpensesMock = vi.fn().mockResolvedValue([
  {
    id: 1,
    user_id: 1,
    date: '2025-01-05',
    amount: -12000,
    category: '식비',
    merchant: 'Merchant A',
    method: 'Card',
    is_fixed: false,
    memo: null,
    created_at: '2025-01-05T00:00:00',
    updated_at: '2025-01-05T00:00:00',
    deleted_at: null,
  },
  {
    id: 2,
    user_id: 1,
    date: '2025-01-06',
    amount: -9000,
    category: '식비',
    merchant: 'Merchant B',
    method: 'Card',
    is_fixed: false,
    memo: null,
    created_at: '2025-01-06T00:00:00',
    updated_at: '2025-01-06T00:00:00',
    deleted_at: '2025-01-07T00:00:00',
  },
]);

const fetchCategoriesMock = vi.fn().mockResolvedValue([]);
const fetchExpenseSummaryMock = vi.fn().mockResolvedValue({
  period: { year: 2025, month: 1 },
  total_expense: 21000,
  total_income: 0,
  net: -21000,
  fixed_expense: 0,
  fixed_ratio: 0,
  category_breakdown: [],
  method_breakdown: [],
  transaction_count: 2,
});

vi.mock('../lib/api', () => {
  return {
    ApiClient: class {
      fetchExpenses = fetchExpensesMock;
      fetchExpenseSummary = fetchExpenseSummaryMock;
      fetchCategories = fetchCategoriesMock;
      deleteExpense = vi.fn().mockResolvedValue({ status: 'ok' });
      restoreExpense = vi.fn().mockResolvedValue({});
      updateExpense = vi.fn().mockResolvedValue({});
      uploadExpenseFile = vi.fn().mockResolvedValue({});
      triggerLearning = vi.fn().mockResolvedValue({ added: 0, updated: 0 });
    },
  };
});

import { ExpensesDashboard } from '../components/ExpensesDashboard';

describe('ExpensesDashboard', () => {
  it('toggles visibility of deleted expenses', async () => {
    render(<ExpensesDashboard serverUrl="http://localhost" apiToken="token" />);

    // 기본적으로 삭제되지 않은 항목(Merchant A)만 표시
    expect(await screen.findByText('Merchant A')).toBeInTheDocument();
    expect(screen.queryByText('Merchant B')).not.toBeInTheDocument();

    // 토글 체크박스 클릭
    const checkbox = screen.getByRole('checkbox');
    fireEvent.click(checkbox);

    // 삭제된 항목(Merchant B)도 표시됨
    expect(await screen.findByText('Merchant B')).toBeInTheDocument();
  });
});
```

#### Verification:
- Run: `npm run test --prefix frontend`
- Run: `npm run typecheck --prefix frontend`
- Expected: No failures.

**🎉 ALL PROMPTS COMPLETED!**
