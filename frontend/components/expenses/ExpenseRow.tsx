import React from 'react';
import { RotateCcw, Trash2 } from 'lucide-react';
import { formatCurrency } from '@/shared/portfolio';
import type { BackendExpense } from '@/shared/api/client';

interface ExpenseRowProps {
    expense: BackendExpense;
    isEditing: boolean;
    draftCategory: string;
    draftAmount: number;
    dynamicCategories: string[];
    isCustomCategoryMode: boolean;
    isSaving: boolean;
    isDeleting: boolean;
    isRestoring: boolean;
    onEdit: (expense: BackendExpense) => void;
    onSave: (id: number) => void;
    onCancel: () => void;
    onDelete: (id: number) => void;
    onRestore: (id: number) => void;
    onDraftCategoryChange: (value: string) => void;
    onDraftAmountToggle: () => void;
    onCustomModeToggle: (enable: boolean) => void;
    isRemoteEnabled: boolean;
}

export const ExpenseRow: React.FC<ExpenseRowProps> = ({
    expense,
    isEditing,
    draftCategory,
    draftAmount,
    dynamicCategories,
    isCustomCategoryMode,
    isSaving,
    isDeleting,
    isRestoring,
    onEdit,
    onSave,
    onCancel,
    onDelete,
    onRestore,
    onDraftCategoryChange,
    onDraftAmountToggle,
    onCustomModeToggle,
    isRemoteEnabled,
}) => {
    const isDeleted = expense.deleted_at != null;
    const rowClass = isDeleted ? 'opacity-50' : '';
    const amountColor = isEditing
        ? (draftAmount < 0 ? 'text-rose-600' : 'text-emerald-600')
        : (expense.amount < 0 ? 'text-rose-600' : 'text-emerald-600');

    const renderAmountCell = () => {
        if (!isEditing) return formatCurrency(expense.amount);

        return (
            <div className="flex flex-col items-end gap-1">
                <div className="flex items-center gap-1">
                    <span className="text-xs font-normal text-slate-400">
                        {draftAmount < 0 ? '지출' : '수입'}
                    </span>
                    <span className="text-sm font-semibold tabular-nums">
                        {formatCurrency(Math.abs(draftAmount))}
                    </span>
                </div>
                <button
                    type="button"
                    onClick={onDraftAmountToggle}
                    className="text-[10px] text-indigo-600 hover:text-indigo-800 underline"
                >
                    부호 전환 (+/-)
                </button>
            </div>
        );
    };

    const renderCategoryCell = () => {
        if (!isEditing) {
            return (
                <div className="flex flex-col items-start gap-1">
                    <span className={`inline-flex items-center px-2 py-1 rounded-md text-xs ${isDeleted ? 'bg-slate-200 text-slate-500 line-through' : 'bg-slate-100 text-slate-600'}`}>
                        {expense.category}
                    </span>
                    {expense.review_reason && !isDeleted && (
                        <span className="text-[11px] text-amber-600">
                            검토 필요 · {expense.review_reason}
                        </span>
                    )}
                    {isDeleted && (
                        <span className="text-[10px] text-slate-400">삭제됨</span>
                    )}
                </div>
            );
        }

        if (isCustomCategoryMode) {
            return (
                <div className="flex items-center gap-1">
                    <input
                        autoFocus
                        value={draftCategory}
                        onChange={(e) => onDraftCategoryChange(e.target.value)}
                        className="w-full min-w-[100px] px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700"
                        placeholder="새 카테고리..."
                    />
                    <button
                        type="button"
                        onClick={() => onCustomModeToggle(false)}
                        className="text-[10px] text-slate-400 hover:text-slate-600 underline whitespace-nowrap"
                    >
                        선택형으로
                    </button>
                </div>
            );
        }

        return (
            <select
                value={draftCategory}
                onChange={(e) => {
                    if (e.target.value === '__custom__') {
                        onCustomModeToggle(true);
                        onDraftCategoryChange('');
                    } else {
                        onDraftCategoryChange(e.target.value);
                    }
                }}
                className="w-full min-w-[120px] px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 bg-white"
            >
                <option value="">-- 선택 --</option>
                {dynamicCategories.map((cat) => (
                    <option key={cat} value={cat}>{cat}</option>
                ))}
                {!dynamicCategories.includes(draftCategory) && draftCategory && (
                    <option value={draftCategory}>{draftCategory}</option>
                )}
                <option value="__custom__">+ 직접 입력하기...</option>
            </select>
        );
    };

    const renderActionCell = () => {
        // 삭제된 항목: 복구 버튼만 표시
        if (isDeleted) {
            return (
                <button
                    type="button"
                    onClick={() => onRestore(expense.id)}
                    disabled={!isRemoteEnabled || isRestoring}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-50 text-emerald-600 hover:bg-emerald-100 disabled:opacity-50"
                >
                    <RotateCcw size={14} />
                    {isRestoring ? '복구 중...' : '복구'}
                </button>
            );
        }

        // 편집 중이 아닐 때: 수정/삭제 버튼
        if (!isEditing) {
            return (
                <div className="flex items-center justify-end gap-2">
                    <button
                        type="button"
                        onClick={() => onEdit(expense)}
                        disabled={!isRemoteEnabled}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-500 hover:text-indigo-600"
                    >
                        수정
                    </button>
                    <button
                        type="button"
                        onClick={() => onDelete(expense.id)}
                        disabled={!isRemoteEnabled || isDeleting}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-rose-500 hover:bg-rose-50 disabled:opacity-50"
                    >
                        <Trash2 size={14} />
                        {isDeleting ? '삭제 중...' : '삭제'}
                    </button>
                </div>
            );
        }

        // 편집 중: 저장/취소 버튼
        return (
            <div className="flex items-center justify-end gap-2">
                <button
                    type="button"
                    onClick={() => onSave(expense.id)}
                    disabled={isSaving || !draftCategory.trim()}
                    className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${isSaving || !draftCategory.trim()
                            ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                            : 'bg-indigo-600 text-white hover:bg-indigo-700'
                        }`}
                >
                    {isSaving ? '저장 중...' : '저장'}
                </button>
                <button
                    type="button"
                    onClick={onCancel}
                    disabled={isSaving}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-500 hover:text-slate-700"
                >
                    취소
                </button>
            </div>
        );
    };

    return (
        <tr className={`text-sm text-slate-600 ${rowClass}`}>
            <td className="p-3 whitespace-nowrap">{expense.date}</td>
            <td className="p-3">
                <div className={`font-medium ${isDeleted ? 'text-slate-500 line-through' : 'text-slate-800'}`}>
                    {expense.merchant || '-'}
                </div>
                {expense.method && <div className="text-xs text-slate-400">{expense.method}</div>}
            </td>
            <td className={`p-3 text-right font-semibold ${amountColor}`}>
                {renderAmountCell()}
            </td>
            <td className="p-3">{renderCategoryCell()}</td>
            <td className="p-3 text-right whitespace-nowrap">{renderActionCell()}</td>
        </tr>
    );
};
