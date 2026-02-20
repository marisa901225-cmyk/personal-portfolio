import React, { useEffect, useMemo, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { ApiClient, BackendFxTransaction, mapBackendFxToFrontend } from '@/shared/api/client';
import { getUserErrorMessage } from '@/shared/errors';
import type { FxTransactionRecord, FxTransactionType } from '../lib/types';
import { FxTransactionForm, FxTransactionRow, type FxDraft } from './exchange';

type FxFilter = 'ALL' | FxTransactionType;

interface ExchangeHistoryProps {
  serverUrl: string;
  apiToken?: string;
  cookieAuth?: boolean;
  onFxBaseUpdated?: (value: number) => void;
}

const PAGE_SIZE = 200;

const typeToCurrency = (type: FxTransactionType): 'KRW' | 'USD' => (
  type === 'BUY' ? 'USD' : 'KRW'
);

const makeDraft = (record?: FxTransactionRecord): FxDraft => {
  const type = record?.type ?? 'BUY';
  return {
    tradeDate: record?.tradeDate ?? new Date().toISOString().slice(0, 10),
    type,
    currency: record?.currency ?? typeToCurrency(type),
    fxAmount: record?.fxAmount != null ? String(record.fxAmount) : '',
    krwAmount: record?.krwAmount != null ? String(record.krwAmount) : '',
    rate: record?.rate != null ? String(record.rate) : '',
    description: record?.description ?? '',
    note: record?.note ?? '',
  };
};

const parseNumber = (value: string): number | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
};

export const ExchangeHistory: React.FC<ExchangeHistoryProps> = ({
  serverUrl,
  apiToken,
  cookieAuth,
  onFxBaseUpdated,
}) => {
  const [records, setRecords] = useState<FxTransactionRecord[]>([]);
  const [cursorBeforeId, setCursorBeforeId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FxFilter>('ALL');
  const [yearFilter, setYearFilter] = useState<number | 'ALL'>('ALL');
  const [monthFilter, setMonthFilter] = useState<number | 'ALL'>('ALL');
  const [searchTerm, setSearchTerm] = useState('');

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<FxDraft | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [newDraft, setNewDraft] = useState<FxDraft>(() => makeDraft());
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeletingId, setIsDeletingId] = useState<string | null>(null);

  const isRemoteEnabled = Boolean(serverUrl && (apiToken || cookieAuth));
  const apiClient = useMemo(() => new ApiClient(serverUrl, apiToken), [serverUrl, apiToken]);

  const loadRecords = async ({ reset }: { reset: boolean }) => {
    if (!isRemoteEnabled || isLoading || (!hasMore && !reset)) return;
    const beforeId = reset ? undefined : cursorBeforeId ?? undefined;
    setIsLoading(true);
    setLoadError(null);
    try {
      const backendRecords = await apiClient.fetchFxTransactions({
        limit: PAGE_SIZE,
        beforeId,
        kind: filter === 'ALL' ? undefined : filter,
      });
      const mapped = backendRecords.map(mapBackendFxToFrontend);
      setRecords((prev) => (reset ? mapped : [...prev, ...mapped]));
      const last = backendRecords[backendRecords.length - 1];
      setCursorBeforeId(last ? last.id : null);
      setHasMore(backendRecords.length === PAGE_SIZE);
    } catch (error) {
      setLoadError(getUserErrorMessage(error, { default: '환전 내역을 불러오지 못했습니다.' }));
    } finally {
      setIsLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRecords([]);
    setCursorBeforeId(null);
    setHasMore(true);
    setEditingId(null);
    setDraft(null);
    setShowNew(false);
    setFormError(null);
    setYearFilter('ALL');
    setMonthFilter('ALL');
    await loadRecords({ reset: true });
  };

  useEffect(() => {
    setRecords([]);
    setCursorBeforeId(null);
    setHasMore(true);
    setLoadError(null);
    setEditingId(null);
    setDraft(null);
    setShowNew(false);
    setFormError(null);
  }, [serverUrl, apiToken]);

  useEffect(() => {
    if (!isRemoteEnabled) return;
    void handleRefresh();
  }, [isRemoteEnabled, filter]);

  const availableYears = useMemo(() => {
    const years = new Set<number>();
    records.forEach((r) => years.add(new Date(r.tradeDate).getFullYear()));
    return Array.from(years).sort((a, b) => b - a);
  }, [records]);

  const filteredRecords = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return records.filter((r) => {
      if (yearFilter !== 'ALL' && new Date(r.tradeDate).getFullYear() !== yearFilter) return false;
      if (monthFilter !== 'ALL' && new Date(r.tradeDate).getMonth() + 1 !== monthFilter) return false;
      if (!query) return true;
      return (r.description || '').toLowerCase().includes(query) || (r.note || '').toLowerCase().includes(query);
    });
  }, [records, searchTerm, yearFilter, monthFilter]);

  const updateDraftField = (field: keyof FxDraft, value: string) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [field]: value };
      if (field === 'type') next.currency = typeToCurrency(value as FxTransactionType);
      return next;
    });
  };

  const updateNewDraftField = (field: keyof FxDraft, value: string) => {
    setNewDraft((prev) => {
      const next = { ...prev, [field]: value };
      if (field === 'type') next.currency = typeToCurrency(value as FxTransactionType);
      return next;
    });
  };

  const startEdit = (record: FxTransactionRecord) => {
    setEditingId(record.id);
    setDraft(makeDraft(record));
    setFormError(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraft(null);
    setFormError(null);
  };

  const toPayload = (input: FxDraft) => ({
    trade_date: input.tradeDate,
    type: input.type,
    currency: typeToCurrency(input.type),
    fx_amount: parseNumber(input.fxAmount),
    krw_amount: parseNumber(input.krwAmount),
    rate: parseNumber(input.rate),
    description: input.description.trim() || null,
    note: input.note.trim() || null,
  });

  const applyFxBaseFromHistory = async () => {
    if (!isRemoteEnabled) return;
    let weightedSum = 0, weightTotal = 0, fallbackSum = 0, fallbackCount = 0;
    let beforeId: number | undefined;
    while (true) {
      const batch: BackendFxTransaction[] = await apiClient.fetchFxTransactions({ limit: 500, beforeId, kind: 'BUY' });
      if (batch.length === 0) break;
      batch.forEach((rec) => {
        const fxAmount = rec.fx_amount ?? null;
        let rate = rec.rate ?? null;
        if (rate == null && fxAmount != null && rec.krw_amount != null && fxAmount !== 0) {
          rate = rec.krw_amount / fxAmount;
        }
        if (rate == null || !Number.isFinite(rate)) return;
        if (fxAmount != null && Number.isFinite(fxAmount) && fxAmount > 0) {
          weightedSum += rate * fxAmount;
          weightTotal += fxAmount;
        } else {
          fallbackSum += rate;
          fallbackCount += 1;
        }
      });
      if (batch.length < 500) break;
      beforeId = batch[batch.length - 1].id;
    }
    const avgRate = weightTotal > 0 ? weightedSum / weightTotal : fallbackCount > 0 ? fallbackSum / fallbackCount : null;
    if (!avgRate || !Number.isFinite(avgRate)) throw new Error('no fx average');
    const rounded = Math.round(avgRate * 100) / 100;
    await apiClient.updateSettings({ usd_fx_base: rounded });
    onFxBaseUpdated?.(rounded);
  };

  const saveEdit = async () => {
    if (!draft || !editingId) return;
    if (!draft.tradeDate) { setFormError('거래일자를 입력해주세요.'); return; }
    setIsSaving(true);
    setFormError(null);
    try {
      await apiClient.updateFxTransaction(Number(editingId), toPayload(draft));
      await handleRefresh();
      try { await applyFxBaseFromHistory(); } catch { setFormError('기준 환율 자동 갱신에 실패했습니다.'); }
      cancelEdit();
    } catch (error) {
      setFormError(getUserErrorMessage(error, { default: '수정에 실패했습니다.' }));
    } finally {
      setIsSaving(false);
    }
  };

  const saveCreate = async () => {
    if (!newDraft.tradeDate) { setFormError('거래일자를 입력해주세요.'); return; }
    setIsSaving(true);
    setFormError(null);
    try {
      await apiClient.createFxTransaction(toPayload(newDraft));
      await handleRefresh();
      try { await applyFxBaseFromHistory(); } catch { setFormError('기준 환율 자동 갱신에 실패했습니다.'); }
      setShowNew(false);
      setNewDraft(makeDraft());
    } catch (error) {
      setFormError(getUserErrorMessage(error, { default: '등록에 실패했습니다.' }));
    } finally {
      setIsSaving(false);
    }
  };

  const deleteRecord = async (recordId: string) => {
    if (!window.confirm('이 환전 내역을 삭제할까요?')) return;
    setIsDeletingId(recordId);
    setFormError(null);
    try {
      await apiClient.deleteFxTransaction(Number(recordId));
      await handleRefresh();
      try { await applyFxBaseFromHistory(); } catch { setFormError('기준 환율 자동 갱신에 실패했습니다.'); }
    } catch (error) {
      setFormError(getUserErrorMessage(error, { default: '삭제에 실패했습니다.' }));
    } finally {
      setIsDeletingId(null);
    }
  };

  const filterOptions: { key: FxFilter; label: string }[] = [
    { key: 'ALL', label: '전체' },
    { key: 'BUY', label: '매수' },
    { key: 'SELL', label: '매도' },
    { key: 'SETTLEMENT', label: '정산' },
  ];

  return (
    <section className="bg-white rounded-2xl shadow-sm border border-slate-100 p-4">
      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800">환전 내역</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            {isRemoteEnabled ? '날짜별 환전 기록을 확인하고 수정할 수 있습니다.' : '서버 연결이 필요합니다. (설정/로그인)'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void handleRefresh()} disabled={isLoading} className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed transition-colors">
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} /> 새로고침
          </button>
          <button type="button" onClick={() => { setShowNew(true); setNewDraft(makeDraft()); setFormError(null); }} className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 transition-colors">
            <Plus size={14} /> 환전 추가
          </button>
        </div>
      </div>

      {!isRemoteEnabled ? (
        <div className="mt-4 text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">환전 내역은 백엔드 서버 연결 시에만 조회/수정할 수 있어요.</div>
      ) : (
        <div className="mt-4 space-y-3">
          {/* Filters */}
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-2">
            <input type="text" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} placeholder="적요/비고 검색..." className="flex-1 max-w-md px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm" />
            <div className="flex flex-wrap items-center gap-2">
              <select value={yearFilter} onChange={(e) => setYearFilter(e.target.value === 'ALL' ? 'ALL' : Number(e.target.value))} className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium">
                <option value="ALL">전체 년도</option>
                {availableYears.map((y) => <option key={y} value={y}>{y}년</option>)}
              </select>
              <select value={monthFilter} onChange={(e) => setMonthFilter(e.target.value === 'ALL' ? 'ALL' : Number(e.target.value))} className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium">
                <option value="ALL">전체 월</option>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}월</option>)}
              </select>
              {filterOptions.map(({ key, label }) => (
                <button key={key} type="button" onClick={() => setFilter(key)} className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors ${filter === key ? 'bg-indigo-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{label}</button>
              ))}
            </div>
          </div>

          {formError && <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl p-3">{formError}</div>}
          {loadError && <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl p-3">{loadError}</div>}

          {showNew && (
            <FxTransactionForm
              draft={newDraft}
              onDraftChange={updateNewDraftField}
              onSave={() => void saveCreate()}
              onCancel={() => { setShowNew(false); setNewDraft(makeDraft()); setFormError(null); }}
              isSaving={isSaving}
              isNew
            />
          )}

          {filteredRecords.length === 0 ? (
            <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">{records.length === 0 ? '환전 내역이 없습니다.' : '조건에 맞는 내역이 없습니다.'}</div>
          ) : (
            <div className="space-y-2">
              {filteredRecords.map((record) => {
                if (editingId === record.id && draft) {
                  return (
                    <FxTransactionForm
                      key={record.id}
                      draft={draft}
                      onDraftChange={updateDraftField}
                      onSave={() => void saveEdit()}
                      onCancel={cancelEdit}
                      isSaving={isSaving}
                    />
                  );
                }
                return (
                  <FxTransactionRow
                    key={record.id}
                    record={record}
                    onEdit={startEdit}
                    onDelete={(id) => void deleteRecord(id)}
                    isDeleting={isDeletingId === record.id}
                  />
                );
              })}
            </div>
          )}

          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>불러온 내역 {records.length.toLocaleString()}건{filteredRecords.length !== records.length && <span className="ml-1">(표시 {filteredRecords.length.toLocaleString()}건)</span>}</span>
            <button type="button" onClick={() => void loadRecords({ reset: false })} disabled={isLoading || !hasMore} className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors">
              {isLoading ? '불러오는 중...' : hasMore ? '더 불러오기' : '끝'}
            </button>
          </div>
        </div>
      )}
    </section>
  );
};
