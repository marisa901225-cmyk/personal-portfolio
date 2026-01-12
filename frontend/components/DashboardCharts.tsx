import React, { useMemo } from 'react';
import { PortfolioSummary } from '../lib/types';
import { formatCurrency } from '@/shared/portfolio';
import {
    PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area,
    XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar, Legend
} from 'recharts';
import { TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react';

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
    const historyStats = useMemo(() => {
        if (!summary.historyData || summary.historyData.length === 0) return null;
        const data = summary.historyData;
        const getValue = (item: typeof data[number]) =>
            typeof item.stockValue === 'number' ? item.stockValue : item.value;
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
            ? `시장지수 (${benchmarkName.trim()}) 대비`
            : '시장지수 대비';
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
                            <span className="font-medium font-mono">
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
                            <h4 className="text-sm font-semibold text-amber-800 mb-1">리밸런싱 제안</h4>
                            <ul className="text-xs text-amber-700 space-y-1">
                                {rebalanceNotices.map((msg, idx) => (
                                    <li key={idx} className="flex items-center gap-2">
                                        <span className="w-1 h-1 bg-amber-400 rounded-full" />
                                        {msg}
                                    </li>
                                ))}
                            </ul>
                        </div>
                    </div>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
                {/* 1. Allocation Chart (Donut) */}
                <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-shadow duration-300 border border-slate-100 flex flex-col h-full group">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                            <span className="w-1 h-5 bg-indigo-500 rounded-full" />
                            포트폴리오 비중
                        </h3>
                        <div className="px-3 py-1 bg-slate-50 rounded-full text-xs font-medium text-slate-500">
                            자산 구성
                        </div>
                    </div>

                    <div className="h-[320px] w-full shrink-0 relative">
                        <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                                <Pie
                                    data={summary.categoryDistribution}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={80}
                                    outerRadius={110}
                                    paddingAngle={4}
                                    dataKey="value"
                                    cornerRadius={6}
                                >
                                    {summary.categoryDistribution.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={entry.color} stroke="none" />
                                    ))}
                                </Pie>
                                <Tooltip content={<CustomTooltip />} />
                            </PieChart>
                        </ResponsiveContainer>

                        {/* Center Text for Donut */}
                        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                            <span className="text-xs text-slate-400 font-medium">TOTAL ASSETS</span>
                            <span className="text-xl font-bold text-slate-800 tabular-nums tracking-tight mt-0.5">
                                {formatCurrency(summary.totalValue)}
                            </span>
                        </div>
                    </div>

                    <div className="mt-4 border-t border-slate-50 pt-4 max-h-[200px] overflow-y-auto custom-scrollbar">
                        <div className="grid grid-cols-2 gap-3">
                            {summary.categoryDistribution.map((item, idx) => (
                                <div key={idx} className="flex items-center justify-between p-2 rounded-xl hover:bg-slate-50 transition-colors">
                                    <div className="flex items-center gap-2 min-w-0">
                                        <div className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
                                        <span className="text-xs text-slate-600 truncate font-medium">{item.name}</span>
                                    </div>
                                    <span className="text-xs font-bold text-slate-800 tabular-nums">
                                        {((item.value / summary.totalValue) * 100).toFixed(1)}%
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                {/* 2. History Chart (Gradient Area) */}
                <div className="bg-white p-6 rounded-3xl shadow-sm hover:shadow-lg transition-shadow duration-300 border border-slate-100 flex flex-col h-full group">
                    <div className="flex items-center justify-between mb-6">
                        <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                            <span className="w-1 h-5 bg-emerald-500 rounded-full" />
                            자산 추이 (1년)
                        </h3>
                        {historyStats && (
                            <div className={`flex items-center gap-1 text-sm font-bold bg-slate-50 px-3 py-1 rounded-full ${historyStats.change >= 0 ? 'text-emerald-600' : 'text-rose-600'
                                }`}>
                                {historyStats.changeRate >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                                {historyStats.changeRate > 0 ? '+' : ''}{historyStats.changeRate.toFixed(1)}%
                            </div>
                        )}
                    </div>

                    <div className="h-[300px] w-full flex items-center justify-center shrink-0">
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
                                        tick={{ fill: '#94a3b8', fontSize: 11 }}
                                        dy={10}
                                        minTickGap={30}
                                    />
                                    <YAxis
                                        hide={true}
                                        domain={['dataMin', 'dataMax']}
                                    />
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
                                            name="부동산(지분)"
                                            stroke="#f59e0b"
                                            strokeWidth={2}
                                            fill="url(#gradientRealEstate)"
                                        />
                                    )}
                                </AreaChart>
                            </ResponsiveContainer>
                        ) : (
                            <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-2">
                                <div className="p-4 bg-slate-50 rounded-full">
                                    <TrendingUp size={24} className="opacity-40" />
                                </div>
                                <span className="text-sm">데이터가 충분하지 않습니다</span>
                            </div>
                        )}
                    </div>

                    {historyStats && (
                        <div className="mt-auto pt-6 grid grid-cols-2 gap-4">
                            <div className="p-3 bg-slate-50 rounded-2xl">
                                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">Total Return</div>
                                <div className={`text-lg font-bold tabular-nums ${historyStats.change >= 0 ? 'text-emerald-600' : 'text-rose-600'}`}>
                                    {historyStats.change > 0 ? '+' : ''}{formatCurrency(historyStats.change)}
                                </div>
                            </div>

                            {benchmarkDiff !== null && (
                                <div className="p-3 bg-slate-50 rounded-2xl">
                                    <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1 truncate" title={benchmarkLabel}>
                                        Vs Benchmark
                                    </div>
                                    <div className={`text-lg font-bold tabular-nums ${benchmarkDiff >= 0 ? 'text-emerald-600' : 'text-blue-600'}`}>
                                        {benchmarkDiff > 0 ? '+' : ''}{benchmarkDiff.toFixed(2)}%p
                                    </div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Yearly Stats (Bar Chart) - Full Width */}
            {yearlyStats && yearlyStats.length > 0 && (
                <div className="bg-white p-8 rounded-3xl shadow-sm hover:shadow-lg transition-shadow duration-300 border border-slate-100 group">
                    <div className="flex items-center justify-between mb-8">
                        <div>
                            <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                                <span className="w-1 h-5 bg-violet-500 rounded-full" />
                                연도별 자산 흐름
                            </h3>
                            <p className="text-sm text-slate-500 mt-1 pl-3">입금, 출금 및 순자산 변동 내역</p>
                        </div>
                    </div>

                    <div className="h-[320px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={yearlyStats} barGap={8}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                <XAxis
                                    dataKey="year"
                                    axisLine={false}
                                    tickLine={false}
                                    tick={{ fill: '#94a3b8', fontSize: 12, fontWeight: 500 }}
                                    dy={10}
                                />
                                <YAxis
                                    axisLine={false}
                                    tickLine={false}
                                    tick={{ fill: '#94a3b8', fontSize: 11 }}
                                    tickFormatter={(value) => `${(value / 1000000).toFixed(0)}M`}
                                />
                                <Tooltip
                                    cursor={{ fill: '#f8fafc', radius: 8 }}
                                    content={<CustomTooltip />}
                                />
                                <Legend
                                    verticalAlign="top"
                                    align="right"
                                    iconType="circle"
                                    wrapperStyle={{ top: -10, fontSize: '12px' }}
                                />
                                <Bar dataKey="deposit" name="입금" fill="#818cf8" radius={[6, 6, 0, 0]} maxBarSize={50} />
                                <Bar dataKey="withdrawal" name="출금" fill="#fda4af" radius={[6, 6, 0, 0]} maxBarSize={50} />
                                <Bar dataKey="net" name="순입금" fill="#34d399" radius={[6, 6, 0, 0]} maxBarSize={50} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}
        </div>
    );
};
