import React from 'react';
import { Pencil, Trash2 } from 'lucide-react';
import { formatCurrency } from '@/shared/portfolio';
import type { FxTransactionRecord, FxTransactionType } from '../../lib/types';

const TYPE_LABEL: Record<FxTransactionType, string> = {
    BUY: '매수',
    SELL: '매도',
    SETTLEMENT: '정산',
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

interface FxTransactionRowProps {
    record: FxTransactionRecord;
    onEdit: (record: FxTransactionRecord) => void;
    onDelete: (recordId: string) => void;
    isDeleting: boolean;
}

export const FxTransactionRow: React.FC<FxTransactionRowProps> = ({
    record,
    onEdit,
    onDelete,
    isDeleting,
}) => {
    const badgeClass = record.type === 'BUY'
        ? 'bg-red-50 text-red-600'
        : record.type === 'SELL'
            ? 'bg-blue-50 text-blue-600'
            : 'bg-slate-100 text-slate-600';

    return (
        <div className="border border-slate-100 rounded-2xl p-3 bg-white">
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
                        onClick={() => onEdit(record)}
                        className="inline-flex items-center gap-1 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 transition-colors"
                    >
                        <Pencil size={14} />
                        수정
                    </button>
                    <button
                        type="button"
                        onClick={() => onDelete(record.id)}
                        disabled={isDeleting}
                        className="inline-flex items-center gap-1 px-3 py-2 rounded-xl bg-rose-50 text-rose-600 text-xs font-medium hover:bg-rose-100 disabled:opacity-60"
                    >
                        <Trash2 size={14} />
                        삭제
                    </button>
                </div>
            </div>
        </div>
    );
};
