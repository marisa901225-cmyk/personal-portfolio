import React, { useMemo } from 'react';
import { PortfolioSummary, DividendEntry } from '../lib/types';
import { formatCurrency } from '@/shared/portfolio';
import { BarChart, Bar, ResponsiveContainer } from 'recharts';
import {
    TrendingUp,
    TrendingDown,
    RefreshCw,
    DollarSign,
    Building2,
    Wallet,
    PiggyBank,
    Layers
} from 'lucide-react';

interface DashboardSummaryProps {
    summary: PortfolioSummary;
    realEstateSummary?: {
        totalValue: number;
        totalInvested: number;
        realizedProfitTotal: number;
    };
    isPositive: boolean;
    profitRate: number;
    totalProfit: number;
    dividendInfo: {
        list: DividendEntry[];
        totalAllTime: number;
        currentYearTotal: number;
        hasData: boolean;
        isFromBackend?: boolean;
    };
    fxInfo: {
        enabled: boolean;
        usdAssetsValue: number;
        fxPnl: number;
        fxRateChange: number;
        usdFxBase: number;
        usdFxNow: number;
    };
    onSyncClick?: () => void;
    actualInvested?: number;
}

export const DashboardSummary: React.FC<DashboardSummaryProps> = ({
    summary,
    isPositive,
    profitRate,
    totalProfit,
    dividendInfo,
    fxInfo,
    onSyncClick,
    realEstateSummary,
    actualInvested,
}) => {
    // 비중 계산 로직 개선
    const distributionData = useMemo(() => {
        // 1. 전체 순자산 (부동산 포함)
        const grandTotal = summary.totalValue;

        // 2. 주식 등 투자 자산 총액 (부동산 제외) - 지수 비중 계산용
        const realEstateValue = realEstateSummary?.totalValue ?? 0;
        const investableTotal = grandTotal - realEstateValue;

        // 카테고리 데이터 보정: 부동산이 있다면 지분 가치로 표시
        const categories = summary.categoryDistribution.map(item => {
            if (item.name === '부동산' && realEstateSummary) {
                return { ...item, value: realEstateSummary.totalValue };
            }
            return item;
        });

        // 지수 데이터
        const indices = summary.indexDistribution || [];

        return { categories, indices, grandTotal, investableTotal };
    }, [summary, realEstateSummary]);

    return (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 items-stretch">
            {/* 1. Hero Card: Total Assets */}
            <div className="relative overflow-hidden rounded-3xl p-6 text-white shadow-xl transition-transform hover:scale-[1.01] duration-300 md:col-span-2 bg-gradient-to-br from-indigo-600 via-purple-600 to-violet-800 flex flex-col justify-between min-h-[200px]">
                <div className="absolute top-0 right-0 -mr-16 -mt-16 w-64 h-64 bg-white/10 blur-3xl rounded-full pointer-events-none"></div>
                <div className="absolute bottom-0 left-0 -ml-10 -mb-10 w-40 h-40 bg-indigo-500/30 blur-2xl rounded-full pointer-events-none"></div>

                <div className="relative z-10 flex flex-col h-full justify-between">
                    <div>
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <div className="p-2 bg-white/10 rounded-xl backdrop-blur-md">
                                    <Wallet size={20} className="text-indigo-100" />
                                </div>
                                <span className="text-indigo-100 font-medium text-sm tracking-wide">총 순자산</span>
                            </div>
                            <div className="flex items-center gap-2">
                                {summary.xirr_rate !== undefined && summary.xirr_rate !== null && (
                                    <div className="flex items-center gap-2 px-3 py-1 bg-white/10 rounded-full backdrop-blur-md border border-white/10">
                                        <span className="text-xs text-indigo-100 font-bold uppercase tracking-wider">XIRR</span>
                                        <span className={`text-sm font-bold ${summary.xirr_rate >= 0 ? 'text-emerald-300' : 'text-blue-300'}`}>
                                            {summary.xirr_rate >= 0 ? '+' : ''}{(summary.xirr_rate * 100).toFixed(2)}%
                                        </span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="mt-6">
                            <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-white tabular-nums drop-shadow-sm leading-tight">
                                {formatCurrency(summary.totalValue)}
                            </h1>
                        </div>
                    </div>

                    <div className="mt-6 flex items-end justify-between">
                        <div className="space-y-2">
                            <div className="space-y-1.5 bg-white/10 p-3 rounded-2xl border border-white/5 backdrop-blur-sm">
                                <div className="flex items-center justify-between gap-4 text-indigo-100 text-[11px] font-medium">
                                    <span className="opacity-70">주식/금융 원금</span>
                                    <span className="font-bold tabular-nums">
                                        {formatCurrency((actualInvested ?? summary.totalInvested) - (realEstateSummary?.totalInvested ?? 0))}
                                    </span>
                                </div>
                                <div className="flex items-center justify-between gap-4 text-indigo-100 text-[11px] font-medium">
                                    <span className="opacity-70">부동산 지분 원금</span>
                                    <span className="font-bold tabular-nums">
                                        {formatCurrency(realEstateSummary?.totalInvested ?? 0)}
                                    </span>
                                </div>
                            </div>
                            <div className="flex flex-wrap items-center gap-2">
                                <div className={`flex items-center gap-1.5 px-3 py-1 bg-white/10 rounded-lg backdrop-blur-md border ${isPositive
                                    ? 'border-emerald-400/30 text-emerald-300'
                                    : 'border-rose-400/30 text-rose-300'
                                    }`}>
                                    {isPositive ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                                    <span className="font-bold tabular-nums text-sm">
                                        {isPositive ? '+' : ''}{Math.abs(profitRate).toFixed(2)}%
                                    </span>
                                </div>
                                {fxInfo.enabled && (
                                    <div className="hidden sm:flex items-center gap-1.5 px-3 py-1 rounded-lg bg-white/5 border border-white/10 backdrop-blur-md text-xs text-indigo-200">
                                        <RefreshCw size={12} className={fxInfo.fxPnl > 0 ? "text-emerald-300" : "text-blue-300"} />
                                        <span className={`font-semibold ${fxInfo.fxPnl >= 0 ? 'text-emerald-300' : 'text-blue-300'}`}>
                                            {fxInfo.fxPnl >= 0 ? '+' : ''}{formatCurrency(fxInfo.fxPnl)}
                                        </span>
                                    </div>
                                )}
                            </div>
                        </div>

                        {onSyncClick && (
                            <button
                                onClick={onSyncClick}
                                className="p-3 bg-white/10 hover:bg-white/20 rounded-2xl text-white transition-all backdrop-blur-md border border-white/10 shadow-lg group"
                            >
                                <RefreshCw size={20} className="group-hover:rotate-180 transition-transform duration-700" />
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* 2. Total Profit Card */}
            <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col justify-between group h-full">
                <div className="flex justify-between items-start">
                    <div className="p-2.5 bg-rose-50 rounded-2xl group-hover:bg-rose-100 transition-colors">
                        <PiggyBank size={24} className="text-rose-500" />
                    </div>
                    <div className={`px-2.5 py-1 rounded-full text-[10px] font-bold tracking-wider ${isPositive ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'
                        }`}>
                        {isPositive ? 'PROFIT' : 'LOSS'}
                    </div>
                </div>

                <div className="mt-4">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Total P&L</p>
                    <h3 className={`text-2xl font-bold mt-1 tabular-nums tracking-tight ${isPositive ? 'text-slate-900' : 'text-rose-600'
                        }`}>
                        {isPositive ? '+' : ''}{formatCurrency(totalProfit)}
                    </h3>
                </div>

                <div className="mt-4 pt-4 border-t border-slate-50 grid grid-cols-2 gap-2 text-[11px]">
                    <div>
                        <span className="text-slate-400 block mb-0.5 font-medium">평가 손익</span>
                        <span className={`font-bold tabular-nums ${summary.unrealizedProfitTotal >= 0 ? 'text-emerald-600' : 'text-blue-600'}`}>
                            {summary.unrealizedProfitTotal >= 0 ? '+' : ''}{formatCurrency(summary.unrealizedProfitTotal)}
                        </span>
                    </div>
                    <div className="text-right">
                        <span className="text-slate-400 block mb-0.5 font-medium">실현 수익</span>
                        <span className={`font-bold tabular-nums ${summary.realizedProfitTotal >= 0 ? 'text-emerald-600' : 'text-blue-600'}`}>
                            {summary.realizedProfitTotal >= 0 ? '+' : ''}{formatCurrency(summary.realizedProfitTotal)}
                        </span>
                    </div>
                </div>
            </div>

            {/* 3. Dividend Card */}
            <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col justify-between group h-full">
                <div className="flex justify-between items-start">
                    <div className="p-2.5 bg-emerald-50 rounded-2xl group-hover:bg-emerald-100 transition-colors">
                        <DollarSign size={24} className="text-emerald-600" />
                    </div>
                    <div className="text-right">
                        <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest">YTD</p>
                        <p className="text-xs font-bold text-emerald-600">+{formatCurrency(dividendInfo.currentYearTotal)}</p>
                    </div>
                </div>

                <div className="mt-4">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Dividends</p>
                    <h3 className="text-2xl font-bold text-slate-900 mt-1 tabular-nums tracking-tight">
                        {dividendInfo.hasData ? `+${formatCurrency(dividendInfo.totalAllTime)}` : '₩0'}
                    </h3>
                </div>

                <div className="mt-4 h-[40px] w-full">
                    {dividendInfo.hasData ? (
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={dividendInfo.list}>
                                <Bar dataKey="total" fill="#10b981" radius={[2, 2, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="h-full flex items-center justify-center text-[10px] text-slate-300 bg-slate-50/50 rounded-lg italic font-medium">
                            No Dividends
                        </div>
                    )}
                </div>
            </div>

            {/* 4. Real Estate Card */}
            <div className={`bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col justify-between group h-full ${!realEstateSummary ? 'opacity-50' : ''}`}>
                <div className="flex justify-between items-start">
                    <div className="p-2.5 bg-blue-50 rounded-2xl group-hover:bg-blue-100 transition-colors">
                        <Building2 size={24} className="text-blue-500" />
                    </div>
                    <div className="px-2.5 py-1 bg-blue-50 text-blue-600 rounded-full text-[10px] font-bold tracking-widest uppercase">
                        Realty
                    </div>
                </div>

                {realEstateSummary ? (
                    <>
                        <div className="mt-4">
                            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">부동산 (지분)</p>
                            <h3 className="text-2xl font-bold text-slate-900 mt-1 tabular-nums tracking-tight">
                                {formatCurrency(realEstateSummary.totalValue)}
                            </h3>
                        </div>
                        <div className="mt-4 pt-4 border-t border-slate-50 flex items-center justify-between text-[11px]">
                            <div>
                                <span className="text-slate-400 block mb-0.5 font-medium">매입 원금</span>
                                <span className="font-bold text-slate-700">{formatCurrency(realEstateSummary.totalInvested)}</span>
                            </div>
                            <div className="text-right">
                                <span className="text-slate-400 block mb-0.5 font-medium">평가 손익</span>
                                <span className={`font-bold ${(realEstateSummary.totalValue - realEstateSummary.totalInvested) >= 0 ? 'text-red-500' : 'text-blue-600'}`}>
                                    {formatCurrency(realEstateSummary.totalValue - realEstateSummary.totalInvested)}
                                </span>
                            </div>
                        </div>
                    </>
                ) : (
                    <div className="mt-4 flex flex-col items-center justify-center h-full gap-2 py-4">
                        <Building2 size={32} className="opacity-10" />
                        <span className="text-[10px] text-slate-300 font-bold uppercase tracking-widest leading-none">Not Added</span>
                    </div>
                )}
            </div>

            {/* 5. Combined Allocation List (Correct Separation of Denominators) */}
            <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 md:col-span-3 lg:col-span-3 flex flex-col h-full group">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <div className="p-2 bg-indigo-50 rounded-xl text-indigo-500">
                            <Layers size={18} />
                        </div>
                        <h3 className="text-sm font-bold text-slate-900">포트폴리오 비중 상세</h3>
                    </div>
                    <div className="flex gap-4">
                        <div className="flex items-center gap-1.5">
                            <div className="w-1.5 h-1.5 rounded-full bg-indigo-500"></div>
                            <span className="text-[10px] font-bold text-slate-400">지수/테마 (투자자산 대비)</span>
                        </div>
                        <div className="flex items-center gap-1.5">
                            <div className="w-1.5 h-1.5 rounded-full bg-slate-300"></div>
                            <span className="text-[10px] font-bold text-slate-400">전체 자산 대비</span>
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 h-full">
                    {/* Index Distribution (Uses investableTotal) */}
                    <div className="md:col-span-2 flex flex-col justify-center">
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                            {distributionData.indices.length > 0 ? (
                                distributionData.indices.map((item, idx) => (
                                    <div key={idx} className="flex items-center justify-between p-2 rounded-xl bg-indigo-50/40 hover:bg-indigo-50/70 transition-colors border border-indigo-100/30">
                                        <span className="text-[11px] font-bold text-indigo-700 truncate mr-2" title={item.name}>{item.name}</span>
                                        <span className="text-[11px] font-bold text-indigo-900 tabular-nums">
                                            {/* 주식 자산(=전체-부동산) 대비 비중 계산 */}
                                            {distributionData.investableTotal > 0
                                                ? ((item.value / distributionData.investableTotal) * 100).toFixed(1)
                                                : '0.0'}%
                                        </span>
                                    </div>
                                ))
                            ) : (
                                <div className="col-span-full py-4 text-center text-[10px] text-slate-300 italic">No Index Data</div>
                            )}
                        </div>
                    </div>

                    {/* Category Distribution (Uses grandTotal) */}
                    <div className="md:col-span-1 border-l border-slate-50 pl-6 flex flex-col justify-center">
                        <div className="space-y-2">
                            {distributionData.categories.map((item, idx) => (
                                <div key={idx} className="flex items-center justify-between p-1.5 hover:bg-slate-50 rounded-lg transition-colors">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: (item as any).color || '#cbd5e1' }} />
                                        <span className="text-[11px] font-bold text-slate-500 truncate">{item.name}</span>
                                    </div>
                                    <span className="text-[11px] font-bold text-slate-800 tabular-nums">
                                        {/* 전체 자산 대비 비중 계산 */}
                                        {((item.value / distributionData.grandTotal) * 100).toFixed(1)}%
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
