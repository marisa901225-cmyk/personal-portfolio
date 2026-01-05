import React from 'react';
import { Save, X } from 'lucide-react';
import type { FxTransactionType } from '../../lib/types';

export type FxDraft = {
    tradeDate: string;
    type: FxTransactionType;
    currency: 'KRW' | 'USD';
    fxAmount: string;
    krwAmount: string;
    rate: string;
    description: string;
    note: string;
};

interface FxTransactionFormProps {
    draft: FxDraft;
    onDraftChange: (field: keyof FxDraft, value: string) => void;
    onSave: () => void;
    onCancel: () => void;
    isSaving: boolean;
    isNew?: boolean;
}

export const FxTransactionForm: React.FC<FxTransactionFormProps> = ({
    draft,
    onDraftChange,
    onSave,
    onCancel,
    isSaving,
    isNew = false,
}) => {
    const containerClass = isNew
        ? 'border border-indigo-100 rounded-2xl p-3 bg-indigo-50/40'
        : 'border border-indigo-100 rounded-2xl p-3 bg-white';

    return (
        <div className={containerClass}>
            {isNew && <div className="text-xs font-semibold text-indigo-600 mb-2">새 환전 내역</div>}
            <div className="grid grid-cols-1 md:grid-cols-8 gap-2 text-xs">
                <div>
                    <label className="block text-[11px] text-slate-500 mb-1">날짜</label>
                    <input
                        type="date"
                        value={draft.tradeDate}
                        onChange={(e) => onDraftChange('tradeDate', e.target.value)}
                        className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                    />
                </div>
                <div>
                    <label className="block text-[11px] text-slate-500 mb-1">구분</label>
                    <select
                        value={draft.type}
                        onChange={(e) => onDraftChange('type', e.target.value)}
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
                        onChange={(e) => onDraftChange('fxAmount', e.target.value)}
                        className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                    />
                </div>
                <div>
                    <label className="block text-[11px] text-slate-500 mb-1">원화금액</label>
                    <input
                        type="number"
                        step="0.01"
                        value={draft.krwAmount}
                        onChange={(e) => onDraftChange('krwAmount', e.target.value)}
                        className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                    />
                </div>
                <div>
                    <label className="block text-[11px] text-slate-500 mb-1">환율</label>
                    <input
                        type="number"
                        step="0.0001"
                        value={draft.rate}
                        onChange={(e) => onDraftChange('rate', e.target.value)}
                        className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                    />
                </div>
                <div>
                    <label className="block text-[11px] text-slate-500 mb-1">적요</label>
                    <input
                        type="text"
                        value={draft.description}
                        onChange={(e) => onDraftChange('description', e.target.value)}
                        className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                    />
                </div>
                <div>
                    <label className="block text-[11px] text-slate-500 mb-1">비고</label>
                    <input
                        type="text"
                        value={draft.note}
                        onChange={(e) => onDraftChange('note', e.target.value)}
                        className="w-full px-2 py-2 border border-slate-200 rounded-lg bg-white"
                    />
                </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
                <button
                    type="button"
                    onClick={onSave}
                    disabled={isSaving}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 disabled:opacity-60"
                >
                    <Save size={14} />
                    저장
                </button>
                <button
                    type="button"
                    onClick={onCancel}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-600 text-xs font-medium hover:bg-slate-200"
                >
                    <X size={14} />
                    취소
                </button>
                <span className="text-[11px] text-slate-400">통화는 구분에 따라 자동 설정됩니다.</span>
            </div>
        </div>
    );
};
