
import React from 'react';
import { Edit3 } from 'lucide-react';
import { formatCurrency } from '@/shared/portfolio';

interface CashEditFormProps {
    inputValue: string;
    setInputValue: (v: string) => void;
    isCmaEnabled: boolean;
    setIsCmaEnabled: (v: boolean) => void;
    annualRate: string;
    setAnnualRate: (v: string) => void;
    taxRate: string;
    setTaxRate: (v: string) => void;
    startDate: string;
    setStartDate: (v: string) => void;
    cmaPreview: number | null;
    onSave: () => void;
}

export const CashEditForm: React.FC<CashEditFormProps> = ({
    inputValue,
    setInputValue,
    isCmaEnabled,
    setIsCmaEnabled,
    annualRate,
    setAnnualRate,
    taxRate,
    setTaxRate,
    startDate,
    setStartDate,
    cmaPreview,
    onSave,
}) => {
    return (
        <div className="space-y-3">
            <label className="block text-sm font-semibold text-slate-700">
                현재 잔액 (KRW)
            </label>

            <div className="relative">
                <input
                    type="text"
                    className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                    placeholder="예: 1000000"
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') onSave();
                    }}
                />
                <div className="absolute right-4 top-1/2 transform -translate-y-1/2 text-slate-400 pointer-events-none">
                    <Edit3 size={18} />
                </div>
            </div>

            <p className="text-xs text-slate-400">
                실제 계좌의 현재 잔액을 입력하면 자동으로 수량이 조정됩니다.
            </p>

            <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
                <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
                        <input
                            type="checkbox"
                            className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500"
                            checked={isCmaEnabled}
                            onChange={(e) => setIsCmaEnabled(e.target.checked)}
                        />
                        <span>발행어음 / CMA 이자 자동 반영</span>
                    </label>
                    <span className="text-[10px] text-slate-400">
                        가격 동기화 시 세후 이자 반영
                    </span>
                </div>

                {isCmaEnabled && (
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                        <div>
                            <label className="block mb-1 text-slate-600">
                                연 이자율 (세전, %)
                            </label>
                            <input
                                type="number"
                                min="0"
                                step="0.01"
                                className="w-full px-3 py-2 rounded-lg border border-slate-200"
                                placeholder="예: 4.5"
                                value={annualRate}
                                onChange={(e) => setAnnualRate(e.target.value)}
                            />
                        </div>
                        <div>
                            <label className="block mb-1 text-slate-600">
                                이자소득세율 (%)
                            </label>
                            <input
                                type="number"
                                min="0"
                                step="0.1"
                                className="w-full px-3 py-2 rounded-lg border border-slate-200"
                                placeholder="기본 15.4"
                                value={taxRate}
                                onChange={(e) => setTaxRate(e.target.value)}
                            />
                        </div>
                        <div>
                            <label className="block mb-1 text-slate-600">
                                이자 계산 시작일
                            </label>
                            <input
                                type="date"
                                className="w-full px-3 py-2 rounded-lg border border-slate-200"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                            />
                        </div>
                    </div>
                )}

                {isCmaEnabled && cmaPreview !== null && (
                    <p className="text-[11px] text-emerald-600">
                        오늘 기준 예상 잔액(세후): <span className="font-semibold">{formatCurrency(cmaPreview)}</span>
                    </p>
                )}
            </div>
        </div>
    );
};
