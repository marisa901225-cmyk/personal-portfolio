import React from 'react';
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
    Layers,
    AlertTriangle,
    X
} from 'lucide-react';
import { usePortfolioCalculations } from '../src/hooks/usePortfolioCalculations';

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
    rebalanceNotices?: string[];
    onDismissWarnings?: () => void;
}

const DashboardSummaryComponent: React.FC<DashboardSummaryProps> = ({
    summary,
    isPositive,
    profitRate,
    totalProfit,
    dividendInfo,
    fxInfo,
    onSyncClick,
    realEstateSummary,
    actualInvested,
    rebalanceNotices = [],
    onDismissWarnings,
}) => {
    const { distributionDetails: distributionData } = usePortfolioCalculations({
        summary,
        actualInvested,
        realEstateSummary
    });

    return (
        <div className="flex flex-col gap-6">
            {/* Rebalance Alert Banner - Dismissible */}
            {rebalanceNotices.length > 0 && (
                <div className="animate-fade-in-down mb-2">
                    <div className="relative overflow-hidden bg-white border border-rose-100 rounded-3xl p-5 shadow-sm group">
                        <div className="absolute top-0 right-0 p-2">
                            <button
                                onClick={onDismissWarnings}
                                className="p-2 hover:bg-slate-100 rounded-full text-slate-400 transition-colors"
                                title="점검 메시지 닫기"
                            >
                                <X size={18} />
                            </button>
                        </div>
                        <div className="flex items-start gap-4">
                            <div className="p-3 bg-rose-50 rounded-2xl text-rose-500 shrink-0">
                                <AlertTriangle size={24} />
                            </div>
                            <div className="flex-1 pt-1">
                                <h4 className="text-sm font-bold text-slate-900 mb-1 flex items-center gap-2">
                                    포트폴리오 점검 제안
                                    <span className="text-[10px] px-1.5 py-0.5 bg-rose-50 text-rose-600 rounded-md font-bold uppercase tracking-wider">Attention</span>
                                </h4>
                                <ul className="space-y-1.5">
                                    {rebalanceNotices.map((msg, idx) => (
                                        <li key={idx} className="text-xs font-semibold text-slate-600 flex items-center gap-2">
                                            <div className="w-1 h-1 bg-rose-400 rounded-full shrink-0" />
                                            {msg}
                                        </li>
                                    ))}
                                </ul>
                                <p className="mt-3 text-[10px] text-slate-400 font-medium italic">
                                    * 이 메시지는 현재 세션에서 한 번만 표시됩니다. 'X'를 누르면 다음 로그인까지 보이지 않습니다.
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Grid Container: 3 Rows */}
            <div className="grid gap-6">
                {/* Row 1: 통합 요약 카드 (전체 너비) */}
                <div className="bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500 rounded-[20px] p-[24px] shadow-sm hover:shadow-xl transition-all duration-300 relative overflow-hidden">
                    {/* Decorative Background Elements */}
                    <div className="absolute top-0 right-0 -mr-20 -mt-20 w-64 h-64 bg-white/10 blur-3xl rounded-full pointer-events-none"></div>
                    <div className="absolute bottom-0 left-0 -ml-16 -mb-16 w-48 h-48 bg-white/5 blur-2xl rounded-full pointer-events-none"></div>

                    <div className="relative z-10 flex flex-col md:flex-row items-center justify-between gap-6">
                        {/* 총 자산 */}
                        <div className="flex-1">
                            <div className="flex items-center gap-3 mb-3">
                                <div className="p-2 bg-white/10 backdrop-blur-sm rounded-xl">
                                    <Wallet size={24} className="text-white" />
                                </div>
                                <span className="text-white/90 font-bold text-base tracking-tight">총 순자산</span>

                                {/* Sync Button - 제목 옆에 배치 */}
                                <button
                                    onClick={onSyncClick}
                                    className="p-2 bg-white/20 backdrop-blur-sm text-white rounded-xl hover:bg-white/30 transition-all hover:scale-105 active:scale-95 shadow-sm border border-white/30"
                                    title="전체 자산 수동 동기화"
                                >
                                    <RefreshCw size={16} className="transition-transform duration-700 active:rotate-180" />
                                </button>
                            </div>
                            <h1 className="text-4xl md:text-5xl font-black tracking-tighter text-white tabular-nums leading-tight mb-4">
                                {formatCurrency(summary.totalValue)}
                            </h1>
                            <div className="flex flex-wrap items-center gap-3">
                                <div className="inline-flex flex-col gap-1.5 p-3 bg-white/10 backdrop-blur-sm rounded-2xl border border-white/20">
                                    <div className="flex items-center justify-between gap-4 text-white/80 text-xs font-bold">
                                        <span>금융 자산</span>
                                        <span className="text-white font-black tabular-nums">
                                            {formatCurrency((actualInvested ?? summary.totalInvested) - (realEstateSummary?.totalInvested ?? 0))}
                                        </span>
                                    </div>
                                    <div className="flex items-center justify-between gap-4 text-white/80 text-xs font-bold">
                                        <span>부동산 지분</span>
                                        <span className="text-white font-black tabular-nums">
                                            {formatCurrency(realEstateSummary?.totalInvested ?? 0)}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* 총 손익 및 수익률 */}
                        <div className="flex-1 flex flex-col md:items-end gap-4">
                            <div className="flex items-center gap-3">
                                {summary.xirr_rate !== undefined && summary.xirr_rate !== null && (
                                    <div className="flex items-center gap-2 px-4 py-2 bg-white/20 backdrop-blur-sm rounded-full border border-white/30">
                                        <span className="text-xs text-white/90 font-black uppercase tracking-widest">XIRR</span>
                                        <span className="text-lg font-black tabular-nums text-white">
                                            {summary.xirr_rate >= 0 ? '+' : ''}{(summary.xirr_rate * 100).toFixed(2)}%
                                        </span>
                                    </div>
                                )}
                                <div className={`flex items-center gap-2 px-4 py-2 bg-white/20 backdrop-blur-sm rounded-full border border-white/30`}>
                                    {isPositive ? <TrendingUp size={18} className="text-white" /> : <TrendingDown size={18} className="text-white" />}
                                    <span className="text-lg font-black text-white tabular-nums">{isPositive ? '+' : ''}{profitRate.toFixed(2)}%</span>
                                </div>
                            </div>
                            <div className="text-right">
                                <p className="text-xs font-bold text-white/70 uppercase tracking-widest mb-1">총 손익</p>
                                <h2 className="text-3xl md:text-4xl font-black text-white tabular-nums tracking-tight">
                                    {isPositive ? '+' : ''}{formatCurrency(totalProfit)}
                                </h2>
                            </div>
                            <div className="flex gap-4 text-sm">
                                <div className="flex flex-col items-end">
                                    <span className="text-white/70 mb-0.5 font-medium text-xs">평가 손익</span>
                                    <span className="font-bold tabular-nums text-white">
                                        {summary.unrealizedProfitTotal >= 0 ? '+' : ''}{formatCurrency(summary.unrealizedProfitTotal)}
                                    </span>
                                </div>
                                <div className="w-px bg-white/20"></div>
                                <div className="flex flex-col items-end">
                                    <span className="text-white/70 mb-0.5 font-medium text-xs">실현 수익</span>
                                    <span className="font-bold tabular-nums text-white">
                                        {summary.realizedProfitTotal >= 0 ? '+' : ''}{formatCurrency(summary.realizedProfitTotal)}
                                    </span>
                                </div>
                            </div>
                            {fxInfo.enabled && (
                                <div className="flex items-center gap-2 px-3 py-1.5 bg-white/10 backdrop-blur-sm rounded-xl border border-white/20">
                                    <DollarSign size={14} className="text-white/80" />
                                    <span className="text-xs font-black tabular-nums text-white/90">{fxInfo.fxPnl >= 0 ? '+' : ''}{formatCurrency(fxInfo.fxPnl)}</span>
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {/* Row 2: 좌우 2컬럼 */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    {/* 좌: 포트폴리오 비중 (차트와 리스트) */}
                    <div className="bg-white p-[24px] rounded-[20px] shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col h-full">
                        <div className="flex items-center gap-2 mb-4">
                            <div className="p-2 bg-indigo-50 rounded-xl">
                                <Layers size={20} className="text-indigo-600" />
                            </div>
                            <h3 className="text-base font-bold text-slate-900">포트폴리오 비중</h3>
                        </div>

                        {/* 지수 리스트 */}
                        <div className="mb-4">
                            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">투자 지수</p>
                            <div className="grid grid-cols-2 gap-2">
                                {distributionData.indices.length > 0 ? (
                                    distributionData.indices.map((item, idx) => (
                                        <div key={idx} className="flex items-center justify-between p-3 rounded-xl bg-indigo-50/60 hover:bg-indigo-50 transition-colors border border-indigo-100/50">
                                            <span className="text-xs font-bold text-indigo-700 truncate mr-2" title={item.name}>{item.name}</span>
                                            <span className="text-sm font-black text-indigo-900 tabular-nums">
                                                {distributionData.investableTotal > 0 ? ((item.value / distributionData.investableTotal) * 100).toFixed(1) : '0.0'}%
                                            </span>
                                        </div>
                                    ))
                                ) : (
                                    <div className="col-span-full py-4 text-center text-xs text-slate-300 italic">지수 데이터 없음</div>
                                )}
                            </div>
                        </div>

                        {/* 카테고리 분류 */}
                        <div className="pt-4 border-t border-slate-100">
                            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">자산 분류</p>
                            <div className="space-y-2">
                                {distributionData.categories.map((item, idx) => (
                                    <div key={idx} className="flex items-center justify-between p-2 hover:bg-slate-50 rounded-lg transition-colors">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: item.color || '#cbd5e1' }} />
                                            <span className="text-xs font-bold text-slate-600 truncate">{item.name}</span>
                                        </div>
                                        <span className="text-sm font-black text-slate-900 tabular-nums">
                                            {((item.value / distributionData.grandTotal) * 100).toFixed(1)}%
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* 우: 수익/배당금 상세 */}
                    <div className="grid grid-cols-1 gap-6">
                        {/* 배당금 카드 */}
                        <div className="bg-white p-[24px] rounded-[20px] shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col h-full">
                            <div className="flex justify-between items-start mb-4">
                                <div className="p-2.5 bg-emerald-50 rounded-2xl">
                                    <DollarSign size={24} className="text-emerald-600" />
                                </div>
                                <div className="text-right">
                                    <p className="text-xs text-slate-400 font-bold tracking-widest">올해</p>
                                    <p className="text-sm font-bold text-emerald-600">+{formatCurrency(dividendInfo.currentYearTotal)}</p>
                                </div>
                            </div>
                            <div>
                                <p className="text-xs font-extrabold text-slate-400 uppercase tracking-widest mb-1">배당금 (누적)</p>
                                <h3 className="text-3xl font-black text-slate-900 tabular-nums tracking-tight">
                                    {dividendInfo.hasData ? `+${formatCurrency(dividendInfo.totalAllTime)}` : '₩0'}
                                </h3>
                            </div>
                            <div className="mt-4 h-[50px] w-full">
                                {dividendInfo.hasData ? (
                                    <ResponsiveContainer width="100%" height="100%">
                                        <BarChart data={dividendInfo.list}>
                                            <Bar dataKey="total" fill="#10b981" radius={[3, 3, 0, 0]} />
                                        </BarChart>
                                    </ResponsiveContainer>
                                ) : (
                                    <div className="h-full flex items-center justify-center text-xs text-slate-300 bg-slate-50/50 rounded-lg italic font-medium">
                                        배당 내역 없음
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* 부동산 카드 */}
                        <div className={`bg-white p-[24px] rounded-[20px] shadow-sm hover:shadow-lg transition-all duration-300 border border-slate-100 flex flex-col h-full ${!realEstateSummary ? 'opacity-50' : ''}`}>
                            <div className="flex justify-between items-start mb-4">
                                <div className="p-2.5 bg-blue-50 rounded-2xl">
                                    <Building2 size={24} className="text-blue-500" />
                                </div>
                                <div className="px-2.5 py-1 bg-blue-50 text-blue-600 rounded-full text-xs font-bold tracking-widest">부동산</div>
                            </div>
                            {realEstateSummary ? (
                                <>
                                    <div>
                                        <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-1">부동산 (지분)</p>
                                        <h3 className="text-3xl font-black text-slate-900 tabular-nums tracking-tight">
                                            {formatCurrency(realEstateSummary.totalValue)}
                                        </h3>
                                    </div>
                                    <div className="mt-4 pt-4 border-t border-slate-50 flex items-center justify-between text-sm">
                                        <div>
                                            <span className="text-slate-400 block mb-0.5 font-medium text-xs">매입 원금</span>
                                            <span className="font-bold text-slate-700">{formatCurrency(realEstateSummary.totalInvested)}</span>
                                        </div>
                                        <div className="text-right">
                                            <span className="text-slate-400 block mb-0.5 font-medium text-xs">평가 손익</span>
                                            <span className={`font-bold ${(realEstateSummary.totalValue - realEstateSummary.totalInvested) >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                                                {(realEstateSummary.totalValue - realEstateSummary.totalInvested) >= 0 ? '+' : ''}{formatCurrency(realEstateSummary.totalValue - realEstateSummary.totalInvested)}
                                            </span>
                                        </div>
                                    </div>
                                </>
                            ) : (
                                <div className="flex-1 flex flex-col items-center justify-center gap-2">
                                    <Building2 size={32} className="opacity-10" />
                                    <span className="text-xs text-slate-300 font-bold tracking-widest">등록된 자산 없음</span>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export const DashboardSummary = React.memo(DashboardSummaryComponent);
