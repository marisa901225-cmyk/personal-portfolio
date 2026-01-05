import React from 'react';
import { PortfolioSummary, DividendEntry } from '../lib/types';
import { formatCurrency, REAL_ESTATE_MY_SHARE } from '../lib/utils/constants';
import { Tooltip, BarChart, Bar, ResponsiveContainer } from 'recharts';
import { Wallet, TrendingUp, ArrowUpRight, ArrowDownRight, Edit2, Building, RefreshCw } from 'lucide-react';

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
    onUpdateDividends?: () => void;
    onSyncClick?: () => void;
    actualInvested?: number;  // 연도별 입출금 합계 (실제 원금)
}

export const DashboardSummary: React.FC<DashboardSummaryProps> = ({
    summary,
    isPositive,
    profitRate,
    totalProfit,
    dividendInfo,
    fxInfo,
    onUpdateDividends,
    onSyncClick,
    realEstateSummary,
    actualInvested,
}) => {
    return (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {/* Total Assets Card */}
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden">
                <div className="flex justify-between items-start z-10 relative">
                    <div>
                        <p className="text-xs font-semibold text-slate-500 mb-1">💰 총 자산</p>
                        <h2 className="text-xl md:text-2xl font-bold text-slate-900 tracking-tight whitespace-nowrap">{formatCurrency(summary.totalValue)}</h2>
                    </div>
                </div>
                <div className="mt-4 flex items-center text-sm">
                    <span className={`flex items-center font-semibold ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
                        {isPositive ? <ArrowUpRight size={16} className="mr-1" /> : <ArrowDownRight size={16} className="mr-1" />}
                        {Math.abs(profitRate).toFixed(2)}%
                    </span>
                    <span className="text-slate-400 ml-2">수익률 (배당포함)</span>
                </div>
                {summary.xirr_rate !== undefined && summary.xirr_rate !== null && (
                    <div className="mt-2 text-sm flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                            <span className="text-[11px] font-bold px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 border border-indigo-100">XIRR</span>
                            <span className={`font-bold ${summary.xirr_rate >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                                {summary.xirr_rate >= 0 ? '+' : ''}{(summary.xirr_rate * 100).toFixed(2)}%
                            </span>
                            <span className="text-slate-400 text-xs">연평균 수익률</span>
                        </div>
                        {onSyncClick && (
                            <button
                                onClick={onSyncClick}
                                className="p-1.5 hover:bg-indigo-50 rounded-lg text-slate-400 hover:text-indigo-600 transition-colors group"
                                title="증권사 내역 동기화"
                            >
                                <RefreshCw size={14} className="group-hover:rotate-180 transition-transform duration-500" />
                            </button>
                        )}
                    </div>
                )}
                {fxInfo.enabled && (
                    <div className="mt-2 text-xs text-slate-500">
                        추정 환차{fxInfo.fxPnl >= 0 ? '익' : '손'} (USD 자산 기준){' '}
                        <span
                            className={`font-semibold ${fxInfo.fxPnl > 0 ? 'text-red-500' : fxInfo.fxPnl < 0 ? 'text-blue-500' : 'text-slate-500'
                                }`}
                        >
                            {fxInfo.fxPnl > 0 ? '+' : fxInfo.fxPnl < 0 ? '-' : ''}
                            {formatCurrency(Math.abs(fxInfo.fxPnl))}
                        </span>
                        <span className="ml-1 text-[10px] text-slate-400">
                            (환율 {fxInfo.usdFxBase?.toFixed(0)} → {fxInfo.usdFxNow?.toFixed(0)})
                        </span>
                    </div>
                )}
            </div>

            {/* Real Estate Card (Optional) */}
            {realEstateSummary && (
                <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden">
                    <div className="flex justify-between items-start z-10 relative">
                        <div>
                            <p className="text-xs font-semibold text-slate-500 mb-1">🏢 부동산/실물자산</p>
                            <h2 className="text-xl md:text-2xl font-bold text-slate-900 tracking-tight whitespace-nowrap">{formatCurrency(realEstateSummary.totalValue)}</h2>
                        </div>
                    </div>
                    <div className="mt-4 text-sm text-slate-400">
                        투자 원금: {formatCurrency(realEstateSummary.totalInvested)}
                    </div>
                    <div className="mt-0.5 text-xs text-slate-500">
                        내 지분(매입): {formatCurrency(REAL_ESTATE_MY_SHARE)}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                        평가손익:{' '}
                        <span className={(realEstateSummary.totalValue - realEstateSummary.totalInvested) >= 0 ? 'text-red-500' : 'text-blue-500'}>
                            {formatCurrency(realEstateSummary.totalValue - realEstateSummary.totalInvested)}
                        </span>
                    </div>
                </div>
            )}

            {/* PnL Card */}
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                <div className="flex justify-between items-start">
                    <div>
                        <p className="text-xs font-semibold text-slate-500 mb-1">📈 총 손익 (실현+평가+배당)</p>
                        <h2 className={`text-xl md:text-2xl font-bold tracking-tight whitespace-nowrap ${isPositive ? 'text-slate-900' : 'text-red-600'}`}>
                            {isPositive ? '+' : ''}{formatCurrency(totalProfit)}
                        </h2>
                    </div>
                </div>
                <div className="mt-4 text-sm text-slate-400">
                    순입금 원금: {formatCurrency(actualInvested ?? summary.totalInvested)}
                </div>
                <div className="mt-1 text-xs text-slate-500 space-y-0.5">
                    <div>
                        실현:{' '}
                        <span className={summary.realizedProfitTotal >= 0 ? 'text-red-500' : 'text-blue-500'}>
                            {formatCurrency(summary.realizedProfitTotal)}
                        </span>
                    </div>
                    <div>
                        평가:{' '}
                        <span className={summary.unrealizedProfitTotal >= 0 ? 'text-red-500' : 'text-blue-500'}>
                            {formatCurrency(summary.unrealizedProfitTotal)}
                        </span>
                    </div>
                    <div>
                        배당:{' '}
                        <span className="text-emerald-600 font-semibold">
                            +{formatCurrency(dividendInfo.totalAllTime)}
                        </span>
                    </div>
                </div>
            </div>

            {/* Dividends Card */}
            <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative">
                <div className="flex justify-between items-start">
                    <div>
                        <p className="text-xs font-semibold text-slate-500 mb-1">
                            💵 배당금 ({dividendInfo.isFromBackend ? '증권사 동기화' : '수동 입력'})
                        </p>
                        <h2 className="text-xl md:text-2xl font-bold text-slate-900 tracking-tight whitespace-nowrap">
                            {dividendInfo.hasData ? `+${formatCurrency(dividendInfo.totalAllTime)}` : '-'}
                        </h2>
                    </div>
                    {onUpdateDividends && (
                        <button
                            onClick={onUpdateDividends}
                            className="p-2 hover:bg-slate-100 rounded-lg text-slate-400 hover:text-indigo-600 transition-colors"
                            title="배당금 수정"
                        >
                            <Edit2 size={18} />
                        </button>
                    )}
                </div>

                {dividendInfo.hasData ? (
                    <div className="mt-4 h-[60px] w-full">
                        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={60}>
                            <BarChart data={dividendInfo.list}>
                                <Tooltip
                                    cursor={{ fill: 'transparent' }}
                                    content={({ active, payload }) => {
                                        if (active && payload && payload.length) {
                                            const data = payload[0].payload;
                                            return (
                                                <div className="bg-white p-2 border border-slate-100 shadow-lg rounded-lg text-xs">
                                                    <p className="font-bold text-slate-700">{data.year}년</p>
                                                    <p className="text-emerald-600">+{formatCurrency(data.total)}</p>
                                                </div>
                                            );
                                        }
                                        return null;
                                    }}
                                />
                                <Bar dataKey="total" fill="#10b981" radius={[4, 4, 0, 0]} barSize={20} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                ) : (
                    <div className="mt-4 text-sm text-slate-400">
                        배당금 내역이 없습니다.
                    </div>
                )}

                {dividendInfo.hasData && (
                    <div className="mt-2 text-xs text-slate-500 text-right">
                        올해({new Date().getFullYear()}): <span className="font-semibold text-emerald-600">+{formatCurrency(dividendInfo.currentYearTotal)}</span>
                    </div>
                )}
            </div>
        </div>
    );
};
