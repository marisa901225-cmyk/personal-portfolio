import React from 'react';
import { PortfolioSummary, DividendEntry } from '../lib/types';
import { formatCurrency, REAL_ESTATE_MY_SHARE } from '@/shared/portfolio';
import { Tooltip, BarChart, Bar, ResponsiveContainer } from 'recharts';
import {
    TrendingUp,
    TrendingDown,
    RefreshCw,
    DollarSign,
    Building2,
    Wallet,
    PiggyBank
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
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
            {/* 1. Hero Card: Total Assets */}
            <div className="relative overflow-hidden rounded-3xl p-6 text-white shadow-xl transition-transform hover:scale-[1.01] duration-300 md:col-span-2 xl:col-span-2 bg-gradient-to-br from-indigo-600 via-purple-600 to-violet-800">
                {/* Decorative Background Elements */}
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
                            {summary.xirr_rate !== undefined && summary.xirr_rate !== null && (
                                <div className="flex items-center gap-2 px-3 py-1 bg-white/10 rounded-full backdrop-blur-md border border-white/10">
                                    <span className="text-xs text-indigo-100">XIRR</span>
                                    <span className={`text-sm font-bold ${summary.xirr_rate >= 0 ? 'text-emerald-300' : 'text-blue-300'}`}>
                                        {summary.xirr_rate >= 0 ? '+' : ''}{(summary.xirr_rate * 100).toFixed(2)}%
                                    </span>
                                </div>
                            )}
                        </div>

                        <div className="mt-8">
                            <h1 className="text-4xl md:text-5xl font-bold tracking-tight text-white tabular-nums drop-shadow-sm">
                                {formatCurrency(summary.totalValue)}
                            </h1>
                        </div>
                    </div>

                    <div className="mt-8 flex items-end justify-between">
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-indigo-100 text-sm">
                                <span>투자 원금(순입금)</span>
                                <span className="font-semibold text-white tabular-nums opacity-90">
                                    {formatCurrency(actualInvested ?? summary.totalInvested)}
                                </span>
                            </div>
                            <div className="flex flex-wrap items-center gap-3">
                                <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg backdrop-blur-md border ${isPositive
                                        ? 'bg-emerald-500/20 border-emerald-400/30 text-emerald-200'
                                        : 'bg-rose-500/20 border-rose-400/30 text-rose-200'
                                    }`}>
                                    {isPositive ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
                                    <span className="font-bold tabular-nums">
                                        {isPositive ? '+' : ''}{Math.abs(profitRate).toFixed(2)}%
                                    </span>
                                </div>
                                {fxInfo.enabled && (
                                    <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 border border-white/10 backdrop-blur-md text-xs text-indigo-200">
                                        <RefreshCw size={12} className={fxInfo.fxPnl > 0 ? "text-emerald-300" : "text-blue-300"} />
                                        <span>환차손익</span>
                                        <span className={`font-semibold ml-1 ${fxInfo.fxPnl >= 0 ? 'text-emerald-300' : 'text-blue-300'}`}>
                                            {fxInfo.fxPnl >= 0 ? '+' : ''}{formatCurrency(fxInfo.fxPnl)}
                                        </span>
                                    </div>
                                )}
                            </div>
                        </div>

                        {onSyncClick && (
                            <button
                                onClick={onSyncClick}
                                className="p-3 bg-white/10 hover:bg-white/20 rounded-2xl text-white transition-all backdrop-blur-md border border-white/10 shadow-lg hover:shadow-xl group"
                                title="자산 동기화"
                            >
                                <RefreshCw size={20} className="group-hover:rotate-180 transition-transform duration-700" />
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* 2. Total Profit Card - Clean & Minimal */}
            <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col justify-between group">
                <div className="flex justify-between items-start">
                    <div className="p-2.5 bg-rose-50 rounded-2xl group-hover:bg-rose-100 transition-colors">
                        <PiggyBank size={24} className="text-rose-500" />
                    </div>
                    <div className={`px-2.5 py-1 rounded-full text-xs font-bold ${isPositive ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600'
                        }`}>
                        {isPositive ? 'PROFIT' : 'LOSS'}
                    </div>
                </div>

                <div className="mt-4">
                    <p className="text-sm font-medium text-slate-500">총 손익 (평가+실현)</p>
                    <h3 className={`text-2xl font-bold mt-1 tabular-nums tracking-tight ${isPositive ? 'text-slate-900' : 'text-rose-600'
                        }`}>
                        {isPositive ? '+' : ''}{formatCurrency(totalProfit)}
                    </h3>
                </div>

                <div className="mt-4 pt-4 border-t border-slate-50 grid grid-cols-2 gap-2 text-xs">
                    <div>
                        <span className="text-slate-400 block mb-0.5">평가 손익</span>
                        <span className={`font-semibold tabular-nums ${summary.unrealizedProfitTotal >= 0 ? 'text-emerald-600' : 'text-blue-600'}`}>
                            {summary.unrealizedProfitTotal >= 0 ? '+' : ''}{formatCurrency(summary.unrealizedProfitTotal)}
                        </span>
                    </div>
                    <div className="text-right">
                        <span className="text-slate-400 block mb-0.5">실현 수익</span>
                        <span className={`font-semibold tabular-nums ${summary.realizedProfitTotal >= 0 ? 'text-emerald-600' : 'text-blue-600'}`}>
                            {summary.realizedProfitTotal >= 0 ? '+' : ''}{formatCurrency(summary.realizedProfitTotal)}
                        </span>
                    </div>
                </div>
            </div>

            {/* 3. Dividend Card - Graph Integration */}
            <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col justify-between group">
                <div className="flex justify-between items-start mb-2">
                    <div className="p-2.5 bg-emerald-50 rounded-2xl group-hover:bg-emerald-100 transition-colors">
                        <DollarSign size={24} className="text-emerald-600" />
                    </div>
                    {dividendInfo.hasData && (
                        <div className="text-right">
                            <p className="text-[10px] text-slate-400 font-medium">올해 배당</p>
                            <p className="text-sm font-bold text-emerald-600">+{formatCurrency(dividendInfo.currentYearTotal)}</p>
                        </div>
                    )}
                </div>

                <div>
                    <p className="text-sm font-medium text-slate-500">총 누적 배당</p>
                    <h3 className="text-2xl font-bold text-slate-900 mt-1 tabular-nums tracking-tight">
                        {dividendInfo.hasData ? `+${formatCurrency(dividendInfo.totalAllTime)}` : '-'}
                    </h3>
                </div>

                <div className="mt-2 h-[50px] w-full">
                    {dividendInfo.hasData ? (
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={dividendInfo.list}>
                                <Bar dataKey="total" fill="#10b981" radius={[2, 2, 0, 0]} />
                                <Tooltip
                                    cursor={{ fill: 'transparent' }}
                                    content={() => null} // Hide tooltip for cleaner mini-chart look
                                />
                            </BarChart>
                        </ResponsiveContainer>
                    ) : (
                        <div className="h-full flex items-center justify-center text-xs text-slate-300 bg-slate-50/50 rounded-lg">
                            내역 없음
                        </div>
                    )}
                </div>
            </div>

            {/* 4. Real Estate Card (Conditional) or Portfolio Notice */}
            {realEstateSummary ? (
                <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col justify-between group">
                    <div className="flex justify-between items-start">
                        <div className="p-2.5 bg-blue-50 rounded-2xl group-hover:bg-blue-100 transition-colors">
                            <Building2 size={24} className="text-blue-500" />
                        </div>
                        <div className="px-2.5 py-1 bg-blue-50 text-blue-600 rounded-full text-xs font-bold">
                            REALTY
                        </div>
                    </div>

                    <div className="mt-4">
                        <p className="text-sm font-medium text-slate-500">보유 부동산 (지분)</p>
                        <h3 className="text-2xl font-bold text-slate-900 mt-1 tabular-nums tracking-tight">
                            {formatCurrency(realEstateSummary.totalValue)}
                        </h3>
                    </div>

                    <div className="mt-4 pt-4 border-t border-slate-50 flex items-center justify-between text-xs">
                        <div>
                            <span className="text-slate-400 block mb-0.5">매입 원금</span>
                            <span className="font-semibold text-slate-700">{formatCurrency(realEstateSummary.totalInvested)}</span>
                        </div>
                        <div className="text-right">
                            <span className="text-slate-400 block mb-0.5">평가 손익</span>
                            <span className={`font-semibold ${(realEstateSummary.totalValue - realEstateSummary.totalInvested) >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                                {formatCurrency(realEstateSummary.totalValue - realEstateSummary.totalInvested)}
                            </span>
                        </div>
                    </div>
                </div>
            ) : (
                // 부동산이 없을 때 보여줄 빈 카드 또는 플레이스홀더
                <div className="bg-slate-50 p-6 rounded-3xl border border-dashed border-slate-200 flex flex-col items-center justify-center text-slate-400 gap-2">
                    <Building2 size={32} className="opacity-20" />
                    <span className="text-xs">등록된 부동산 자산이 없습니다</span>
                </div>
            )}
        </div>
    );
};
