import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Loader2,
  TrendingUp,
  TrendingDown,
  CreditCard,
  Wallet,
  Receipt,
  DollarSign,
  ArrowUpRight,
  ArrowDownRight,
  Calendar,
  Filter
} from 'lucide-react';
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  Bar
} from 'recharts';
import {
  ApiClient,
  BackendExpense,
  BackendExpenseSummaryResponse,
  BackendExpenseUploadResult,
} from '@/shared/api/client';
import { COLORS, formatCurrency } from '@/shared/portfolio';
import { getUserErrorMessage } from '@/shared/errors';
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
  const hasMountedRef = useRef(false);
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
    if (!hasMountedRef.current) {
      hasMountedRef.current = true;
      return;
    }

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

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-slate-900/90 backdrop-blur-md p-3 rounded-xl border border-white/10 shadow-xl text-xs text-white z-50">
          <p className="font-semibold mb-2 text-slate-300">{payload[0].name}</p>
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold font-mono">
              {formatCurrency(payload[0].value)}
            </span>
          </div>
        </div>
      );
    }
    return null;
  };

  return (
    <section className="space-y-6 pb-20">
      {/* 1. Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-4 rounded-3xl border border-slate-100 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="p-3 bg-indigo-50 rounded-2xl text-indigo-600">
            <Calendar size={24} />
          </div>
          <div>
            <h2 className="font-bold text-slate-900">가계부 관리</h2>
            <p className="text-xs text-slate-500">월별 수입/지출 내역을 관리합니다.</p>
          </div>
        </div>

        <div className="flex items-center gap-2 bg-slate-50 p-1.5 rounded-2xl border border-slate-100">
          <select
            value={selectedYearMonth.year}
            onChange={(e) => setSelectedMonth(`${Number(e.target.value)}-${String(selectedYearMonth.month).padStart(2, '0')}`)}
            disabled={!isRemoteEnabled}
            className="px-4 py-2 bg-white rounded-xl text-sm font-semibold text-slate-700 shadow-sm border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            {yearOptions.map((y) => <option key={y} value={y}>{y}년</option>)}
          </select>
          <span className="text-slate-300">/</span>
          <select
            value={selectedYearMonth.month}
            onChange={(e) => setSelectedMonth(`${selectedYearMonth.year}-${String(Number(e.target.value)).padStart(2, '0')}`)}
            disabled={!isRemoteEnabled}
            className="px-4 py-2 bg-white rounded-xl text-sm font-semibold text-slate-700 shadow-sm border border-slate-200 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}월</option>)}
          </select>
        </div>
      </div>

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

      {summaryError && (
        <div className="bg-amber-50 text-amber-700 p-4 rounded-2xl text-sm flex items-start gap-3 border border-amber-100">
          <AlertCircle size={20} className="shrink-0 mt-0.5" />
          <span>{summaryError}</span>
        </div>
      )}

      {/* 2. Summary Cards (Bento Grid) */}
      {expenseSummary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 animate-fade-in-up">
          {/* Net Income (Hero) */}
          <div className="bg-gradient-to-br from-indigo-600 via-violet-600 to-purple-700 rounded-3xl p-6 text-white shadow-lg relative overflow-hidden md:col-span-1 flex flex-col justify-between group">
            <div className="absolute top-0 right-0 -mt-10 -mr-10 w-40 h-40 bg-white/10 rounded-full blur-3xl group-hover:scale-110 transition-transform duration-700"></div>

            <div className="flex items-center justify-between relative z-10">
              <div className="p-2.5 bg-white/10 rounded-xl backdrop-blur-md">
                <Wallet size={20} className="text-indigo-100" />
              </div>
              <div className="px-3 py-1 bg-white/10 rounded-full text-xs font-semibold backdrop-blur-md border border-white/10 text-indigo-100">
                순수입 (Net)
              </div>
            </div>

            <div className="mt-8 relative z-10">
              <p className="text-indigo-100 text-sm mb-1">이번 달 남은 돈</p>
              <h3 className="text-3xl font-bold tabular-nums tracking-tight">
                {formatCurrency(expenseSummary.net)}
              </h3>
            </div>
          </div>

          {/* Income */}
          <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100 flex flex-col justify-between hover:scale-[1.01] transition-transform duration-300">
            <div className="flex items-center justify-between">
              <div className="p-2.5 bg-emerald-50 rounded-xl text-emerald-600">
                <ArrowDownRight size={24} />
              </div>
              <span className="text-xs font-bold text-emerald-600 bg-emerald-50 px-2.5 py-1 rounded-full">INCOME</span>
            </div>
            <div className="mt-6">
              <p className="text-slate-500 text-sm font-medium">총 수입</p>
              <h3 className="text-2xl font-bold text-slate-800 tabular-nums mt-1">
                {formatCurrency(expenseSummary.total_income)}
              </h3>
            </div>
          </div>

          {/* Expense */}
          <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-100 flex flex-col justify-between hover:scale-[1.01] transition-transform duration-300">
            <div className="flex items-center justify-between">
              <div className="p-2.5 bg-rose-50 rounded-xl text-rose-500">
                <Receipt size={24} />
              </div>
              <span className="text-xs font-bold text-rose-500 bg-rose-50 px-2.5 py-1 rounded-full">EXPENSE</span>
            </div>
            <div className="mt-6">
              <p className="text-slate-500 text-sm font-medium">총 지출</p>
              <h3 className="text-2xl font-bold text-slate-800 tabular-nums mt-1">
                {formatCurrency(expenseSummary.total_expense)}
              </h3>
              <div className="mt-2 text-xs text-slate-400 flex items-center gap-1">
                <span className="font-medium text-slate-600">{expenseSummary.fixed_ratio.toFixed(1)}%</span>
                가 고정 지출입니다
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 3. Charts & Breakdown */}
      {expenseSummary && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 animate-fade-in-up delay-75">
          <div className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100 flex flex-col h-full hover:shadow-lg transition-shadow duration-300">
            <div className="flex items-center justify-between mb-6">
              <h3 className="font-bold text-slate-800 flex items-center gap-2">
                <span className="w-1 h-5 bg-rose-500 rounded-full"></span>
                지출 카테고리 분석
              </h3>
            </div>

            <div className="flex-1 flex flex-col items-center">
              <div className="h-[280px] w-full relative">
                {expenseSummary.category_breakdown.length > 0 ? (
                  <>
                    <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                      <span className="text-xs text-slate-400 font-medium">TOTAL SPENDING</span>
                      <span className="text-xl font-bold text-slate-800 tabular-nums tracking-tight mt-0.5">
                        {formatCurrency(expenseSummary.total_expense)}
                      </span>
                    </div>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={expenseSummary.category_breakdown as any[]}
                          dataKey="amount"
                          nameKey="category"
                          cx="50%"
                          cy="50%"
                          innerRadius={70}
                          outerRadius={100}
                          paddingAngle={3}
                          cornerRadius={5}
                        >
                          {expenseSummary.category_breakdown.map((_, index) => (
                            <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="none" />
                          ))}
                        </Pie>
                        <Tooltip content={<CustomTooltip />} />
                      </PieChart>
                    </ResponsiveContainer>
                  </>
                ) : (
                  <div className="h-full flex items-center justify-center text-slate-300 text-sm">
                    데이터가 없습니다
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="bg-white p-6 rounded-3xl shadow-sm border border-slate-100 flex flex-col h-full hover:shadow-lg transition-shadow duration-300">
            <div className="flex items-center justify-between mb-6">
              <h3 className="font-bold text-slate-800 flex items-center gap-2">
                <span className="w-1 h-5 bg-slate-500 rounded-full"></span>
                카테고리별 상세
              </h3>
              <div className="text-xs font-medium text-slate-500 bg-slate-100 px-3 py-1 rounded-full">
                {expenseSummary.transaction_count}건의 거래
              </div>
            </div>

            <div className="flex-1 overflow-y-auto max-h-[300px] custom-scrollbar pr-2 space-y-3">
              {expenseSummary.category_breakdown.length > 0 ? (
                expenseSummary.category_breakdown.map((item, index) => (
                  <div key={item.category} className="flex items-center justify-between p-3 rounded-2xl hover:bg-slate-50 transition-colors group border border-transparent hover:border-slate-100">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold text-white shadow-sm" style={{ backgroundColor: COLORS[index % COLORS.length] }}>
                        {item.category.slice(0, 1)}
                      </div>
                      <span className="text-sm font-semibold text-slate-700 group-hover:text-slate-900">{item.category}</span>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-bold text-slate-800 tabular-nums">
                        {formatCurrency(item.amount)}
                      </div>
                      <div className="text-[10px] text-slate-400 font-medium">
                        {((item.amount / expenseSummary.total_expense) * 100).toFixed(1)}%
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="text-center py-10 text-slate-400 text-sm">
                  내역이 없습니다.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 4. Transactions List (Styled Table) */}
      <div className="bg-white rounded-3xl shadow-sm border border-slate-100 p-6 animate-fade-in-up delay-100">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <h3 className="text-lg font-bold text-slate-900">지출/수입 상세 내역</h3>
            <p className="text-sm text-slate-500 mt-1">상세 내역을 수정하거나 삭제할 수 있습니다.</p>
          </div>

          <div className="flex items-center gap-2">
            <label className="flex items-center gap-2 cursor-pointer bg-slate-50 px-4 py-2 rounded-xl hover:bg-slate-100 transition-colors">
              <input
                type="checkbox"
                checked={showDeleted}
                onChange={(e) => setShowDeleted(e.target.checked)}
                className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-sm text-slate-600 font-medium">삭제된 내역 보기</span>
            </label>
          </div>
        </div>

        {!isLoading && displayedExpenses.length === 0 && !loadError && (
          <div className="py-20 text-center flex flex-col items-center justify-center border-2 border-dashed border-slate-100 rounded-3xl">
            <div className="p-4 bg-slate-50 rounded-full mb-3 text-slate-400">
              <Filter size={32} />
            </div>
            <div className="text-slate-900 font-medium mb-1">표시할 내역이 없습니다</div>
            <div className="text-xs text-slate-500">상단의 [내역 업로드] 버튼을 눌러 데이터를 추가해주세요.</div>
          </div>
        )}

        {displayedExpenses.length > 0 && (
          <div className="overflow-hidden rounded-2xl border border-slate-200">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse min-w-[720px]">
                <thead className="bg-slate-50/80 backdrop-blur-sm border-b border-slate-200">
                  <tr>
                    <th className="p-4 text-xs font-bold text-slate-500 uppercase tracking-wider">날짜</th>
                    <th className="p-4 text-xs font-bold text-slate-500 uppercase tracking-wider">가맹점</th>
                    <th className="p-4 text-xs font-bold text-slate-500 uppercase tracking-wider text-right">금액</th>
                    <th className="p-4 text-xs font-bold text-slate-500 uppercase tracking-wider">카테고리</th>
                    <th className="p-4 text-xs font-bold text-slate-500 uppercase tracking-wider text-right">편집</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
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
          </div>
        )}

        {isLoading && (
          <div className="flex items-center justify-center py-20 text-indigo-600">
            <Loader2 size={32} className="animate-spin" />
          </div>
        )}
      </div>
    </section>
  );
};
