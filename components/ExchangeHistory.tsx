import React, { useEffect, useMemo, useState } from 'react';
import { Pencil, Plus, RefreshCw, Save, Trash2, X } from 'lucide-react';
import { ApiClient, BackendFxTransaction, mapBackendFxToFrontend } from '../backendClient';
import { formatCurrency } from '../constants';
import { getUserErrorMessage } from '../errors';
import type { FxTransactionRecord, FxTransactionType } from '../types';

type FxFilter = 'ALL' | FxTransactionType;

type FxDraft = {
  tradeDate: string;
  type: FxTransactionType;
  currency: 'KRW' | 'USD';
  fxAmount: string;
  krwAmount: string;
  rate: string;
  description: string;
  note: string;
};

interface ExchangeHistoryProps {
  serverUrl: string;
  apiToken?: string;
  onFxBaseUpdated?: (value: number) => void;
}

const PAGE_SIZE = 200;

const TYPE_LABEL: Record<FxTransactionType, string> = {
  BUY: '매수',
  SELL: '매도',
  SETTLEMENT: '정산',
};

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

const formatFxAmount = (value?: number) => {
  if (value == null) return '-';
  const formatted = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 }).format(value);
  return `$${formatted}`;
};

const formatRate = (value?: number) => {
  if (value == null) return '-';
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 }).format(value);
};

export const ExchangeHistory: React.FC<ExchangeHistoryProps> = ({
  serverUrl,
  apiToken,
  onFxBaseUpdated,
}) => {
  const [records, setRecords] = useState<FxTransactionRecord[]>([]);
  const [cursorBeforeId, setCursorBeforeId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FxFilter>('ALL');
  const [yearFilter, setYearFilter] = useState<number | 'ALL'>('ALL');
  const [searchTerm, setSearchTerm] = useState('');

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<FxDraft | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [newDraft, setNewDraft] = useState<FxDraft>(() => makeDraft());
  const [formError, setFormError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeletingId, setIsDeletingId] = useState<string | null>(null);

  const isRemoteEnabled = Boolean(serverUrl && apiToken);

  const apiClient = useMemo(() => new ApiClient(serverUrl, apiToken), [serverUrl, apiToken]);

  const loadRecords = async ({ reset }: { reset: boolean }) => {
    if (!isRemoteEnabled) return;
    if (isLoading) return;
    if (!hasMore && !reset) return;

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
      setLoadError(
        getUserErrorMessage(error, {
          default: '환전 내역을 불러오지 못했습니다.',
          unauthorized: '환전 내역을 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '환전 내역을 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
        }),
      );
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRemoteEnabled, filter]);

  const availableYears = useMemo(() => {
    const years = new Set<number>();
    records.forEach((record) => {
      const year = new Date(record.tradeDate).getFullYear();
      years.add(year);
    });
    return Array.from(years).sort((a, b) => b - a);
  }, [records]);

  const filteredRecords = useMemo(() => {
    const query = searchTerm.trim().toLowerCase();
    return records.filter((record) => {
      // 년도 필터
      if (yearFilter !== 'ALL') {
        const recordYear = new Date(record.tradeDate).getFullYear();
        if (recordYear !== yearFilter) return false;
      }
      // 검색어 필터
      if (!query) return true;
      const description = (record.description || '').toLowerCase();
      const note = (record.note || '').toLowerCase();
      return description.includes(query) || note.includes(query);
    });
  }, [records, searchTerm, yearFilter]);

  const updateDraftField = (
    setter: React.Dispatch<React.SetStateAction<FxDraft | null>>,
    field: keyof FxDraft,
    value: string,
  ) => {
    setter((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [field]: value };
      if (field === 'type') {
        const nextType = value as FxTransactionType;
        next.currency = typeToCurrency(nextType);
      }
      return next;
    });
  };

  const updateNewDraftField = (field: keyof FxDraft, value: string) => {
    setNewDraft((prev) => {
      const next = { ...prev, [field]: value };
      if (field === 'type') {
        const nextType = value as FxTransactionType;
        next.currency = typeToCurrency(nextType);
      }
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

  const startCreate = () => {
    setShowNew(true);
    setNewDraft(makeDraft());
    setFormError(null);
  };

  const cancelCreate = () => {
    setShowNew(false);
    setNewDraft(makeDraft());
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

  const saveEdit = async () => {
    if (!draft || !editingId) return;
    if (!draft.tradeDate) {
      setFormError('거래일자를 입력해주세요.');
      return;
    }
    setIsSaving(true);
    setFormError(null);
    try {
      await apiClient.updateFxTransaction(Number(editingId), toPayload(draft));
      await handleRefresh();
      try {
        await applyFxBaseFromHistory();
      } catch (error) {
        setFormError('기준 환율 자동 갱신에 실패했습니다.');
      }
      cancelEdit();
    } catch (error) {
      setFormError(
        getUserErrorMessage(error, {
          default: '수정에 실패했습니다.',
          unauthorized: '수정에 실패했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '수정에 실패했습니다.\n서버 연결을 확인해주세요.',
        }),
      );
    } finally {
      setIsSaving(false);
    }
  };

  const saveCreate = async () => {
    if (!newDraft.tradeDate) {
      setFormError('거래일자를 입력해주세요.');
      return;
    }
    setIsSaving(true);
    setFormError(null);
    try {
      await apiClient.createFxTransaction(toPayload(newDraft));
      await handleRefresh();
      try {
        await applyFxBaseFromHistory();
      } catch (error) {
        setFormError('기준 환율 자동 갱신에 실패했습니다.');
      }
      setShowNew(false);
      setNewDraft(makeDraft());
    } catch (error) {
      setFormError(
        getUserErrorMessage(error, {
          default: '등록에 실패했습니다.',
          unauthorized: '등록에 실패했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '등록에 실패했습니다.\n서버 연결을 확인해주세요.',
        }),
      );
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
      try {
        await applyFxBaseFromHistory();
      } catch (error) {
        setFormError('기준 환율 자동 갱신에 실패했습니다.');
      }
    } catch (error) {
      setFormError(
        getUserErrorMessage(error, {
          default: '삭제에 실패했습니다.',
          unauthorized: '삭제에 실패했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '삭제에 실패했습니다.\n서버 연결을 확인해주세요.',
        }),
      );
    } finally {
      setIsDeletingId(null);
    }
  };

  const applyFxBaseFromHistory = async () => {
    if (!isRemoteEnabled) return;

    let weightedSum = 0;
    let weightTotal = 0;
    let fallbackSum = 0;
    let fallbackCount = 0;
    let beforeId: number | undefined;

    while (true) {
      const batch: BackendFxTransaction[] = await apiClient.fetchFxTransactions({
        limit: 500,
        beforeId,
        kind: 'BUY',
      });
      if (batch.length === 0) break;

      batch.forEach((record) => {
        const fxAmount = record.fx_amount ?? null;
        let rate = record.rate ?? null;
        if (rate == null && fxAmount != null && record.krw_amount != null && fxAmount !== 0) {
          rate = record.krw_amount / fxAmount;
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

    const avgRate = weightTotal > 0
      ? weightedSum / weightTotal
      : fallbackCount > 0
        ? fallbackSum / fallbackCount
        : null;

    if (!avgRate || !Number.isFinite(avgRate)) {
      throw new Error('no fx average');
    }

    const rounded = Math.round(avgRate * 100) / 100;
    await apiClient.updateSettings({ usd_fx_base: rounded });
    onFxBaseUpdated?.(rounded);
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
          <button
            type="button"
            onClick={() => void handleRefresh()}
            disabled={isLoading}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            새로고침
          </button>
          <button
            type="button"
            onClick={startCreate}
            className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 transition-colors"
          >
            <Plus size={14} />
            환전 추가
          </button>
        </div>
      </div>

      {!isRemoteEnabled ? (
        <div className="mt-4 text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
          환전 내역은 백엔드 서버 연결 시에만 조회/수정할 수 있어요.
        </div>
      ) : (
        <div className="mt-4 space-y-3">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-2">
            <div className="relative flex-1 max-w-md">
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="적요/비고 검색..."
                className="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {/* 년도 필터 */}
              <select
                value={yearFilter}
                onChange={(e) => setYearFilter(e.target.value === 'ALL' ? 'ALL' : Number(e.target.value))}
                className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="ALL">전체 년도</option>
                {availableYears.map((year) => (
                  <option key={year} value={year}>{year}년</option>
                ))}
              </select>
              {/* 거래 유형 필터 */}
              {filterOptions.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setFilter(key)}
                  className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors ${filter === key
                    ? 'bg-indigo-600 text-white'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                    }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {formError && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl p-3">
              {formError}
            </div>
          )}

          {loadError && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl p-3">
              {loadError}
            </div>
          )}

          {showNew && (
            <div className="border border-indigo-100 rounded-2xl p-3 bg-indigo-50/40">
              <div className="text-xs font-semibold text-indigo-600 mb-2">새 환전 내역</div>
              <div className="grid grid-cols-1 md:grid-cols-8 gap-2 text-xs">
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">날짜</label>
                  <input
                    type="date"
                    value={newDraft.tradeDate}
                    onChange={(e) => updateNewDraftField('tradeDate', e.target.value)}
                    className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">구분</label>
                  <select
                    value={newDraft.type}
                    onChange={(e) => updateNewDraftField('type', e.target.value)}
                    className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                  >
                    <option value="BUY">매수</option>
                    <option value="SELL">매도</option>
                    <option value="SETTLEMENT">정산</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">통화</label>
                  <div className="px-2 py-2 border border-slate-200 rounded-lg bg-slate-50 text-slate-600">
                    {newDraft.currency}
                  </div>
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">외화금액</label>
                  <input
                    type="number"
                    step="0.0001"
                    value={newDraft.fxAmount}
                    onChange={(e) => updateNewDraftField('fxAmount', e.target.value)}
                    className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">원화금액</label>
                  <input
                    type="number"
                    step="0.01"
                    value={newDraft.krwAmount}
                    onChange={(e) => updateNewDraftField('krwAmount', e.target.value)}
                    className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">환율</label>
                  <input
                    type="number"
                    step="0.0001"
                    value={newDraft.rate}
                    onChange={(e) => updateNewDraftField('rate', e.target.value)}
                    className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">적요</label>
                  <input
                    type="text"
                    value={newDraft.description}
                    onChange={(e) => updateNewDraftField('description', e.target.value)}
                    className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                  />
                </div>
                <div>
                  <label className="block text-[11px] text-slate-500 mb-1">비고</label>
                  <input
                    type="text"
                    value={newDraft.note}
                    onChange={(e) => updateNewDraftField('note', e.target.value)}
                    className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                  />
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => void saveCreate()}
                  disabled={isSaving}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-60"
                >
                  <Save size={14} />
                  저장
                </button>
                <button
                  type="button"
                  onClick={cancelCreate}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-600 text-xs font-medium hover:bg-slate-200"
                >
                  <X size={14} />
                  취소
                </button>
                <span className="text-[11px] text-slate-400">통화는 구분에 따라 자동 설정됩니다.</span>
              </div>
            </div>
          )}

          {filteredRecords.length === 0 ? (
            <div className="text-sm text-slate-500 bg-slate-50 border border-slate-200 rounded-xl p-3">
              {records.length === 0 ? '환전 내역이 없습니다.' : '조건에 맞는 내역이 없습니다.'}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredRecords.map((record) => {
                const isEditing = editingId === record.id;
                const badgeClass = record.type === 'BUY'
                  ? 'bg-red-50 text-red-600'
                  : record.type === 'SELL'
                    ? 'bg-blue-50 text-blue-600'
                    : 'bg-slate-100 text-slate-600';

                if (isEditing && draft) {
                  return (
                    <div key={record.id} className="border border-indigo-100 rounded-2xl p-3 bg-white">
                      <div className="grid grid-cols-1 md:grid-cols-8 gap-2 text-xs">
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">날짜</label>
                          <input
                            type="date"
                            value={draft.tradeDate}
                            onChange={(e) => updateDraftField(setDraft, 'tradeDate', e.target.value)}
                            className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">구분</label>
                          <select
                            value={draft.type}
                            onChange={(e) => updateDraftField(setDraft, 'type', e.target.value)}
                            className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                          >
                            <option value="BUY">매수</option>
                            <option value="SELL">매도</option>
                            <option value="SETTLEMENT">정산</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">통화</label>
                          <div className="px-2 py-2 border border-slate-200 rounded-lg bg-slate-50 text-slate-600">
                            {draft.currency}
                          </div>
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">외화금액</label>
                          <input
                            type="number"
                            step="0.0001"
                            value={draft.fxAmount}
                            onChange={(e) => updateDraftField(setDraft, 'fxAmount', e.target.value)}
                            className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">원화금액</label>
                          <input
                            type="number"
                            step="0.01"
                            value={draft.krwAmount}
                            onChange={(e) => updateDraftField(setDraft, 'krwAmount', e.target.value)}
                            className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">환율</label>
                          <input
                            type="number"
                            step="0.0001"
                            value={draft.rate}
                            onChange={(e) => updateDraftField(setDraft, 'rate', e.target.value)}
                            className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">적요</label>
                          <input
                            type="text"
                            value={draft.description}
                            onChange={(e) => updateDraftField(setDraft, 'description', e.target.value)}
                            className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] text-slate-500 mb-1">비고</label>
                          <input
                            type="text"
                            value={draft.note}
                            onChange={(e) => updateDraftField(setDraft, 'note', e.target.value)}
                            className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                          />
                        </div>
                      </div>
                      <div className="mt-3 flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => void saveEdit()}
                          disabled={isSaving}
                          className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-60"
                        >
                          <Save size={14} />
                          저장
                        </button>
                        <button
                          type="button"
                          onClick={cancelEdit}
                          className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-600 text-xs font-medium hover:bg-slate-200"
                        >
                          <X size={14} />
                          취소
                        </button>
                        <span className="text-[11px] text-slate-400">통화는 구분에 따라 자동 설정됩니다.</span>
                      </div>
                    </div>
                  );
                }

                return (
                  <div key={record.id} className="border border-slate-100 rounded-2xl p-3 bg-white">
                    <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${badgeClass}`}>
                            {TYPE_LABEL[record.type]}
                          </span>
                          <span className="text-[11px] text-slate-500">{record.tradeDate}</span>
                          <span className="px-1.5 py-0.5 rounded bg-slate-100 text-[10px] text-slate-500 font-medium">
                            {record.currency}
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-600">
                          <span>외화 <span className="font-medium">{formatFxAmount(record.fxAmount)}</span></span>
                          <span>원화 <span className="font-medium">{record.krwAmount != null ? formatCurrency(record.krwAmount) : '-'}</span></span>
                          <span>환율 <span className="font-medium">{formatRate(record.rate)}</span></span>
                        </div>
                        {record.description && (
                          <div className="mt-1 text-[11px] text-slate-500">
                            {record.description}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => startEdit(record)}
                          className="inline-flex items-center gap-1 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 transition-colors"
                        >
                          <Pencil size={14} />
                          수정
                        </button>
                        <button
                          type="button"
                          onClick={() => void deleteRecord(record.id)}
                          disabled={isDeletingId === record.id}
                          className="inline-flex items-center gap-1 px-3 py-2 rounded-xl bg-rose-50 text-rose-600 text-xs font-medium hover:bg-rose-100 disabled:opacity-60"
                        >
                          <Trash2 size={14} />
                          삭제
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>
              불러온 내역 {records.length.toLocaleString()}건
              {filteredRecords.length !== records.length && (
                <span className="ml-1">(표시 {filteredRecords.length.toLocaleString()}건)</span>
              )}
            </span>
            <button
              type="button"
              onClick={() => void loadRecords({ reset: false })}
              disabled={isLoading || !hasMore}
              className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            >
              {isLoading ? '불러오는 중...' : hasMore ? '더 불러오기' : '끝'}
            </button>
          </div>
        </div>
      )}
    </section>
  );
};
