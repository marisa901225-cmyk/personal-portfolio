import React, { useMemo } from 'react';
import { PortfolioSummary } from '../lib/types';
import { formatCurrency } from '@/shared/portfolio';
import {
    PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area,
    XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar, Legend
} from 'recharts';
import { TrendingUp, TrendingDown, AlertTriangle, PieChart as PieIcon, LineChart as LineIcon, BarChart3, ArrowUp, ArrowDown, Wallet } from 'lucide-react';

interface DashboardChartsProps {
    summary: PortfolioSummary;
    rebalanceNotices: string[];
    yearlyStats?: {
        year: string;
        deposit: number;
        withdrawal: number;
        net: number;
        note?: string;
    }[];
    benchmarkName?: string;
    benchmarkReturn?: number;
    actualInvested?: number;
}

export const DashboardCharts: React.FC<DashboardChartsProps> = ({
    summary,
    rebalanceNotices,
    yearlyStats,
    benchmarkName,
    benchmarkReturn,
    actualInvested,
}) => {
    // 수익률 및 총 손익 계산 (차트 센터 표시용)
    const { totalProfit, profitRate, isPositive } = useMemo(() => {
        const invested = actualInvested ?? summary.totalInvested;
        const profit = summary.totalValue - invested;
        const rate = invested > 0 ? (profit / invested) * 100 : 0;
        return {
            totalProfit: profit,
            profitRate: rate,
            isPositive: profit >= 0
        };
    }, [summary, actualInvested]);

    const historyStats = useMemo(() => {
        if (!summary.historyData || summary.historyData.length === 0) return null;
        const data = summary.historyData;
        const getValue = (item: typeof data[number]) =>
            typeof item.stockValue === 'number' ? item.stockValue + (item.realEstateValue ?? 0) : item.value;
        const start = getValue(data[0]);
        const end = getValue(data[data.length - 1]);
        const values = data.map(d => getValue(d));
        const max = Math.max(...values);
        const min = Math.min(...values);
        const change = end - start;
        const changeRate = start !== 0 ? (change / start) * 100 : 0;

        return { start, end, max, min, change, changeRate };
    }, [summary.historyData]);

    const benchmarkDiff = useMemo(() => {
        if (!historyStats) return null;
        if (benchmarkReturn === undefined || !Number.isFinite(benchmarkReturn)) return null;

        const baseReturn = (summary.xirr_rate !== undefined && summary.xirr_rate !== null)
            ? summary.xirr_rate * 100
            : historyStats.changeRate;

        return baseReturn - benchmarkReturn;
    }, [historyStats, benchmarkReturn, summary.xirr_rate]);

    const showRealEstate = useMemo(
        () => summary.historyData.some(item => (item.realEstateValue ?? 0) > 0),
        [summary.historyData],
    );

    const benchmarkLabel = useMemo(() => {
        const base = benchmarkName?.trim()
            ? `시장 (${benchmarkName.trim()}) 대비`
            : '시장 대비';
        return (summary.xirr_rate !== undefined && summary.xirr_rate !== null)
            ? `${base} (XIRR)`
            : base;
    }, [benchmarkName, summary.xirr_rate]);

    const CustomTooltip = ({ active, payload, label }: any) => {
        if (active && payload && payload.length) {
            return (
                <div className="bg-slate-900/90 backdrop-blur-md p-3 rounded-xl border border-white/10 shadow-xl text-xs text-white z-50">
                    <p className="font-semibold mb-2 text-slate-300">{label}</p>
                    {payload.map((entry: any, index: number) => (
                        <div key={index} className="flex items-center gap-3 mb-1 justify-between min-w-[120px]">
                            <div className="flex items-center gap-1.5">
                                <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: entry.color }} />
                                <span className="opacity-80">{entry.name}</span>
                            </div>
                            <span className="font-bold font-mono">
                                {formatCurrency(entry.value)}
                            </span>
                        </div>
                    ))}
                </div>
            );
        }
        return null;
    };

    return (
        <div className="space-y-6">
            {/* Rebalance Warnings */}
            {rebalanceNotices.length > 0 && (
                <div className="animate-fade-in-up">
                    <div className="bg-amber-50/50 backdrop-blur-sm border border-amber-100 rounded-2xl p-4 flex items-start gap-3 shadow-sm">
                        <div className="p-2 bg-amber-100/50 rounded-xl text-amber-600 shrink-0">
                            <AlertTriangle size={18} />
                        </div>
                        <div>
                            <h4 className="text-sm font-semibold text-amber-800 mb-1">리밸런싱 점검 제안</h4>
                            <ul className="text-xs text-amber-700 space-y-1">
                                {rebalanceNotices.map((msg, idx) => (
                                    <li key={idx} className="flex items-center gap-2">
                                        <span className="w-1 h-1 bg-amber-400 rounded-full shrink-0" />
                                        <span>{msg}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
                {/* 1. Allocation Chart (Visual-focused) */}
                <div className="bg-white p-0 rounded-3xl shadow-sm hover:shadow-lg transition-shadow duration-300 border border-slate-100 flex flex-col h-full group relative overflow-hidden">
                    <div className="p-6 pb-0 z-10 relative">
                        <div className="flex items-center justify-between">
                            <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                                <PieIcon size={20} className="text-indigo-500" />
                                포트폴리오 비주얼
                            </h3>
                        </div>
                    </div>

                    <div className="flex-1 w-full relative min-h-[360px]">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={summary.categoryDistribution}
                                    cx="50%"
                                    cy="42%"
                                    innerRadius={105}
                                    outerRadius={155}
                                    paddingAngle={3}
                                    dataKey="value"
                                    cornerRadius={12}
                                    stroke="none"
                                >
                                    {summary.categoryDistribution.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={entry.color} stroke="none" />
                                    ))}
                                </Pie>
                                <Tooltip content={<CustomTooltip />} />
                            </PieChart>
                        </ResponsiveContainer>

                        {/* Center Text - Enhanced Content */}
                        <div className="absolute inset-x-0 flex flex-col items-center justify-center pointer-events-none gap-2" style={{ top: '42%', transform: 'translateY(-50%)' }}>
                            <div className="p-2 bg-slate-50 rounded-full shadow-inner mb-1">
                                <Wallet size={16} className="text-slate-400" />
                            </div>

                            <div className="flex flex-col items-center">
                                <span className="text-[10px] text-slate-400 font-bold tracking-widest uppercase">Net Worth</span>
                                <span className="text-2xl font-bold text-slate-900 tabular-nums tracking-tighter">
                                    {formatCurrency(summary.totalValue)}
                                </span>
                            </div>

                            <div className={`flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold shadow-sm border ${isPositive
                                ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                                : 'bg-rose-50 text-rose-600 border-rose-100'
                                }`}>
                                {isPositive ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                                <span>{isPositive ? '+' : ''}{profitRate.toFixed(2)}%</span>
                            </div>
                        </div>

                        {/* Bottom Decoration: Rounded Horizon (Stable Ground) */}
                        <div className="absolute bottom-0 left-0 right-0 h-32 opacity-10 pointer-events-none">
                            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 320" className="w-full h-full" preserveAspectRatio="none">
                                <path fill="#6366f1" fillOpacity="1" d="M0,224L60,229.3C120,235,240,245,360,240C480,235,600,213,720,208C840,203,960,213,1080,224C1200,235,1320,245,1380,250.7L1440,256L1440,320L1380,320C1320,320,1200,320,1080,320C960,320,840,320,720,320C600,320,480,320,360,320C240,320,120,320,60,320L0,320Z"></path>
                            </svg>
                        </div>

                        {/* Ambient Blur Accents */}
                        <div className="absolute bottom-10 left-10 w-24 h-24 bg-indigo-500/10 rounded-full blur-2xl pointer-events-none"></div>
                        <div className="absolute bottom-20 right-10 w-32 h-32 bg-purple-500/10 rounded-full blur-3xl pointer-events-none"></div>

                        {/* Illustration: Chart Observer (Sitting) - Flipped to look at the chart */}
                        <img
                            src="/chart_observer_sitting.png"
                            alt="Portfolio Observer"
                            className="absolute -bottom-3 left-6 w-40 opacity-90 pointer-events-none z-20 mix-blend-multiply grayscale-[0.1]"
                            style={{ transform: 'scaleX(-1)' }}
                        />

                        {/* Illustration: Floor Lamp & Pet (Right side) - Flipped to shine from the right */}
                        <img
                            src="/floor_lamp_cat_v4.png"
                            alt="Cozy Floor Lamp with Pet"
                            className="absolute -bottom-2 right-8 w-44 opacity-95 pointer-events-none z-20 mix-blend-multiply"
                            style={{ transform: 'scaleX(-1)' }}
                        />
                    </div>
                </div>

                {/* 2. History Chart */}
                <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-shadow duration-300 border border-slate-100 flex flex-col h-full group">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                            <LineIcon size={20} className="text-emerald-500" />
                            자산 추이 (1년)
                        </h3>
                        {/* Legend */}
                        <div className="flex items-center gap-3">
                            <div className="flex items-center gap-1.5">
                                <div className="w-2 h-2 rounded-full bg-indigo-500" />
                                <span className="text-[10px] font-bold text-slate-400">주식</span>
                            </div>
                            {showRealEstate && (
                                <div className="flex items-center gap-1.5">
                                    <div className="w-2 h-2 rounded-full bg-amber-500" />
                                    <span className="text-[10px] font-bold text-slate-400">부동산</span>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="h-[280px] w-full flex items-center justify-center shrink-0 mt-2">
                        {summary.historyData.length > 0 ? (
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={summary.historyData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                                    <defs>
                                        <linearGradient id="gradientStock" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="0%" stopColor="#6366f1" stopOpacity={0.4} />
                                            <stop offset="100%" stopColor="#6366f1" stopOpacity={0} />
                                        </linearGradient>
                                        <linearGradient id="gradientRealEstate" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
                                            <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                    <XAxis
                                        dataKey="date"
                                        axisLine={false}
                                        tickLine={false}
                                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                                        dy={10}
                                        minTickGap={40}
                                    />
                                    <YAxis hide={true} domain={['dataMin', 'dataMax']} />
                                    <Tooltip content={<CustomTooltip />} />
                                    <Area
                                        type="monotone"
                                        dataKey="stockValue"
                                        name="주식 자산"
                                        stroke="#6366f1"
                                        strokeWidth={3}
                                        fill="url(#gradientStock)"
                                        activeDot={{ r: 6, strokeWidth: 0, fill: '#6366f1' }}
                                    />
                                    {showRealEstate && (
                                        <Area
                                            type="monotone"
                                            dataKey="realEstateValue"
                                            name="부동산"
                                            stroke="#f59e0b"
                                            strokeWidth={2}
                                            fill="url(#gradientRealEstate)"
                                        />
                                    )}
                                </AreaChart>
                            </ResponsiveContainer>
                        ) : (
                            <div className="flex flex-col items-center justify-center h-full text-slate-300 gap-2">
                                <TrendingUp size={32} className="opacity-20" />
                                <span className="text-xs italic">Not Enough History Data</span>
                            </div>
                        )}
                    </div>

                    {historyStats && (
                        <div className="mt-4 pt-4 border-t border-slate-50 flex-1">
                            <div className="grid grid-cols-2 gap-4">
                                <div className="space-y-4">
                                    <div className="p-4 bg-slate-50/80 rounded-2xl border border-slate-100/50">
                                        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">Total Variation</div>
                                        <div className={`text-xl font-bold tabular-nums ${historyStats.change >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                                            {historyStats.change > 0 ? '+' : ''}{formatCurrency(historyStats.change)}
                                        </div>
                                        <div className={`text-[11px] font-bold ${historyStats.change >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                                            ({historyStats.changeRate > 0 ? '+' : ''}{historyStats.changeRate.toFixed(2)}%)
                                        </div>
                                    </div>

                                    {benchmarkDiff !== null ? (
                                        <div className="p-4 bg-indigo-50/40 rounded-2xl border border-indigo-100/30">
                                            <div className="text-[10px] uppercase tracking-wider text-indigo-500 font-bold mb-1 truncate" title={benchmarkLabel}>
                                                Vs Benchmark
                                            </div>
                                            <div className={`text-xl font-bold tabular-nums ${benchmarkDiff >= 0 ? 'text-indigo-600' : 'text-blue-600'}`}>
                                                {benchmarkDiff > 0 ? '+' : ''}{benchmarkDiff.toFixed(2)}%p
                                            </div>
                                            <div className="text-[11px] font-medium text-indigo-400">
                                                Market: {benchmarkReturn?.toFixed(1)}%
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="p-4 bg-slate-50/30 rounded-2xl border border-dashed border-slate-200 flex flex-col justify-center min-h-[85px]">
                                            <span className="text-[10px] text-slate-400 font-semibold text-center italic">No Benchmark Set</span>
                                        </div>
                                    )}
                                </div>

                                <div className="space-y-3">
                                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider pl-1">Key Statistics</p>
                                    <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50/50 hover:bg-slate-50 transition-colors">
                                        <div className="flex items-center gap-2">
                                            <div className="p-1.5 bg-emerald-100/50 rounded-lg text-emerald-600">
                                                <ArrowUp size={14} />
                                            </div>
                                            <span className="text-xs font-semibold text-slate-500">Period High</span>
                                        </div>
                                        <span className="text-xs font-bold text-slate-800 tabular-nums">{formatCurrency(historyStats.max)}</span>
                                    </div>
                                    <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50/50 hover:bg-slate-50 transition-colors">
                                        <div className="flex items-center gap-2">
                                            <div className="p-1.5 bg-rose-100/50 rounded-lg text-rose-500">
                                                <ArrowDown size={14} />
                                            </div>
                                            <span className="text-xs font-semibold text-slate-500">Period Low</span>
                                        </div>
                                        <span className="text-xs font-bold text-slate-800 tabular-nums">{formatCurrency(historyStats.min)}</span>
                                    </div>
                                    <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50/50 hover:bg-slate-50 transition-colors">
                                        <div className="flex items-center gap-2">
                                            <div className="p-1.5 bg-indigo-100/50 rounded-lg text-indigo-500">
                                                <TrendingUp size={14} />
                                            </div>
                                            <span className="text-xs font-semibold text-slate-500">Ending Balance</span>
                                        </div>
                                        <span className="text-xs font-bold text-slate-800 tabular-nums">{formatCurrency(historyStats.end)}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Yearly Stats Card */}
            {yearlyStats && yearlyStats.length > 0 && (
                <div className="bg-white p-6 md:p-8 rounded-3xl shadow-sm border border-slate-100 group">
                    <div className="flex items-center justify-between mb-8">
                        <div>
                            <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                                <BarChart3 size={20} className="text-violet-500" />
                                연도별 자산 흐름
                            </h3>
                            <p className="text-xs text-slate-500 mt-1 pl-7">입금/출금 및 순입금 히스토리</p>
                        </div>
                    </div>

                    <div className="h-[280px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={yearlyStats} barGap={8}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                <XAxis
                                    dataKey="year"
                                    axisLine={false}
                                    tickLine={false}
                                    tick={{ fill: '#94a3b8', fontSize: 11, fontWeight: 600 }}
                                    dy={10}
                                />
                                <YAxis
                                    axisLine={false}
                                    tickLine={false}
                                    tick={{ fill: '#94a3b8', fontSize: 10 }}
                                    tickFormatter={(value) => `${(value / 10000).toFixed(0)}만`}
                                />
                                <Tooltip
                                    cursor={{ fill: '#f8fafc', radius: 8 }}
                                    content={<CustomTooltip />}
                                />
                                <Legend
                                    verticalAlign="top"
                                    align="right"
                                    iconType="circle"
                                    wrapperStyle={{ top: -20, fontSize: '11px', fontWeight: 600, color: '#64748b' }}
                                />
                                <Bar dataKey="deposit" name="입금" fill="#818cf8" radius={[4, 4, 0, 0]} maxBarSize={40} />
                                <Bar dataKey="withdrawal" name="출금" fill="#fda4af" radius={[4, 4, 0, 0]} maxBarSize={40} />
                                <Bar dataKey="net" name="순입금" fill="#34d399" radius={[4, 4, 0, 0]} maxBarSize={40} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}
        </div>
    );
};
