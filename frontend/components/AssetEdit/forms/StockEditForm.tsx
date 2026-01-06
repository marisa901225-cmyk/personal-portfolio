
import React from 'react';
import { Edit3 } from 'lucide-react';
import { AssetCategory } from '../../../lib/types';

interface StockEditFormProps {
    inputValue: string;
    setInputValue: (v: string) => void;
    amountInput: string;
    setAmountInput: (v: string) => void;
    purchasePriceInput: string;
    setPurchasePriceInput: (v: string) => void;
    category: AssetCategory;
    setCategory: (v: AssetCategory) => void;
    indexGroup: string;
    setIndexGroup: (v: string) => void;
    indexGroupOptions?: string[];
    onSave: () => void;
}

export const StockEditForm: React.FC<StockEditFormProps> = ({
    inputValue,
    setInputValue,
    amountInput,
    setAmountInput,
    purchasePriceInput,
    setPurchasePriceInput,
    category,
    setCategory,
    indexGroup,
    setIndexGroup,
    indexGroupOptions,
    onSave,
}) => {
    return (
        <div className="space-y-3">
            <label className="block text-sm font-semibold text-slate-700">
                종목 티커 (Ticker)
            </label>

            <div className="relative">
                <input
                    type="text"
                    className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                    placeholder="예: 005930, NAS:AAPL"
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
                정확한 시세 조회를 위해 올바른 티커를 입력해주세요.
            </p>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <label className="block text-sm font-semibold text-slate-700 mb-2">
                        보유 수량
                    </label>
                    <input
                        type="number"
                        min="0"
                        step="any"
                        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                        placeholder="0"
                        value={amountInput}
                        onChange={(e) => setAmountInput(e.target.value)}
                    />
                </div>
                <div>
                    <label className="block text-sm font-semibold text-slate-700 mb-2">
                        매수 평균가 (선택)
                    </label>
                    <input
                        type="number"
                        min="0"
                        className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all"
                        placeholder="입력 시 수익률이 계산됩니다."
                        value={purchasePriceInput}
                        onChange={(e) => setPurchasePriceInput(e.target.value)}
                    />
                </div>
            </div>

            <div className="mt-4">
                <label className="block text-sm font-semibold text-slate-700 mb-2">
                    지수 그룹 (Index Group)
                </label>
                <input
                    type="text"
                    list="indexGroupOptions"
                    className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all bg-white"
                    placeholder="예: S&P500, NASDAQ100"
                    value={indexGroup}
                    onChange={(e) => setIndexGroup(e.target.value)}
                />
                <datalist id="indexGroupOptions">
                    {indexGroupOptions?.map((opt) => (
                        <option key={opt} value={opt} />
                    ))}
                </datalist>
                <p className="text-xs text-slate-400 mt-1">포트폴리오 비중 계산에 사용됩니다. 직접 입력하거나 선택하세요.</p>
            </div>

            <div className="mt-4">
                <label className="block text-sm font-semibold text-slate-700 mb-2">
                    자산 카테고리
                </label>
                <select
                    className="w-full px-4 py-3 rounded-xl border-2 border-slate-200 text-base focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all bg-white"
                    value={category}
                    onChange={(e) => setCategory(e.target.value as AssetCategory)}
                >
                    <option value={AssetCategory.STOCK_KR}>국내주식</option>
                    <option value={AssetCategory.STOCK_US}>해외주식</option>
                    <option value={AssetCategory.OTHER}>기타</option>
                </select>
                <p className="text-xs text-slate-400 mt-1">재분류가 필요한 경우 선택하세요. 해외주식으로 변경하면 매수 시 USD 입력 필드가 표시됩니다.</p>
            </div>
        </div>
    );
};
