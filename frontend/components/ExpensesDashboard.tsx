import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, Loader2 } from 'lucide-react';
import { ApiClient, BackendExpense, BackendExpenseUploadResult } from '../lib/api';
import { formatCurrency } from '../lib/utils/constants';
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
    setSaveError(null);
    setEditingId(null);
    setDraftCategory('');
    try {
      // 항상 삭제된 항목도 포함해서 조회 (토글로 표시/숨김 처리)
      const data = await apiClient.fetchExpenses({ year, month, includeDeleted: true }, { signal: controller.signal });
      setExpenses(data);
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
