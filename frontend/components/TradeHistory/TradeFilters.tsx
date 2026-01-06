
import React from 'react';
import type { TradeType } from '../../lib/types';
import { RefreshCw, Search } from 'lucide-react';

export type TradeFilter = 'ALL' | TradeType;

interface TradeFiltersProps {
    searchTerm: string;
    onSearchChange: (value: string) => void;
    yearFilter: number | 'ALL';
    onYearChange: (value: number | 'ALL') => void;
    monthFilter: number | 'ALL';
    onMonthChange: (value: number | 'ALL') => void;
    tradeFilter: TradeFilter;
    onTradeFilterChange: (value: TradeFilter) => void;
    availableYears: number[];
    onRefresh: () => void;
    isRefreshing: boolean;
}

const TRADE_FILTERS: { key: TradeFilter; label: string }[] = [
    { key: 'ALL', label: '전체' },
    { key: 'BUY', label: '매수' },
    { key: 'SELL', label: '매도' },
];

export const TradeFilters: React.FC<TradeFiltersProps> = ({
    searchTerm,
    onSearchChange,
    yearFilter,
    onYearChange,
    monthFilter,
    onMonthChange,
    tradeFilter,
    onTradeFilterChange,
    availableYears,
    onRefresh,
    isRefreshing,
}) => {
    return (
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-2">
            <div className="flex flex-col md:flex-row md:items-center gap-2 flex-1">
                <div className="relative flex-1 max-w-sm">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                    <input
                        type="text"
                        value={searchTerm}
                        onChange={(e) => onSearchChange(e.target.value)}
                        placeholder="자산명/티커 검색..."
                        className="w-full pl-9 pr-3 py-2 bg-slate-50 border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 text-sm"
                    />
                </div>

                <div className="flex items-center gap-2">
                    <select
                        value={yearFilter}
                        onChange={(e) => onYearChange(e.target.value === 'ALL' ? 'ALL' : Number(e.target.value))}
                        className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-[11px] font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                        <option value="ALL">전체 년도</option>
                        {availableYears.map((year) => (
                            <option key={year} value={year}>{year}년</option>
                        ))}
                    </select>

                    <select
                        value={monthFilter}
                        onChange={(e) => onMonthChange(e.target.value === 'ALL' ? 'ALL' : Number(e.target.value))}
                        className="px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-[11px] font-medium focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                        <option value="ALL">전체 월</option>
                        {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => (
                            <option key={month} value={month}>{month}월</option>
                        ))}
                    </select>
                </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1">
                    {TRADE_FILTERS.map(({ key, label }) => (
                        <button
                            key={key}
                            type="button"
                            onClick={() => onTradeFilterChange(key)}
                            className={`px-3 py-2 rounded-xl text-xs font-medium transition-colors ${tradeFilter === key
                                ? 'bg-indigo-600 text-white'
                                : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                                }`}
                        >
                            {label}
                        </button>
                    ))}
                </div>

                <button
                    type="button"
                    onClick={onRefresh}
                    disabled={isRefreshing}
                    className="inline-flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-100 text-slate-700 text-xs font-medium hover:bg-slate-200 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
                >
                    <RefreshCw size={14} className={isRefreshing ? 'animate-spin' : ''} />
                    새로고침
                </button>
            </div>
        </div>
    );
};
