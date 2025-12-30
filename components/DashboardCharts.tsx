import React, { useMemo } from 'react';
import { PortfolioSummary } from '../types';
import { formatCurrency } from '../constants';
import { PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, BarChart, Bar, Legend } from 'recharts';
import { TrendingUp, TrendingDown } from 'lucide-react';

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

        // XIRR이 있으면 XIRR(%)을 기준으로, 없으면 기간 변동(ROI)을 기준으로 비교
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
            ? `시장지수 대비 (${benchmarkName.trim()})`
            : '시장지수 대비';
        return (summary.xirr_rate !== undefined && summary.xirr_rate !== null)
            ? `${base} (XIRR 기준)`
            : base;
    }, [benchmarkName, summary.xirr_rate]);

    return (
        <div className="space-y-6">
            {/* Rebalance Warnings - Moved to Top of Charts Section */}
            {rebalanceNotices.length > 0 && (
                <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-800">
                    <p className="font-semibold mb-1">목표 비중 점검</p>
                    <ul className="list-disc list-inside space-y-0.5">
                        {rebalanceNotices.map((msg, idx) => (
                            <li key={idx}>{msg} 리밸런싱이 필요한지 한 번 점검해 보세요.</li>
                        ))}
                    </ul>
                </div>
            )}

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-stretch">
                {/* Allocation Chart */}
                <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 flex flex-col h-full">
                    <h3 className="text-lg font-bold text-slate-800 mb-6">포트폴리오 비중</h3>
                    <div className="h-[300px] w-full shrink-0">
                        <ResponsiveContainer width="100%" height="100%" minHeight={300} minWidth={0}>
                            <PieChart>
                                <Pie
                                    data={summary.categoryDistribution}
                                    cx="50%"
                                    cy="50%"
                                    innerRadius={60}
                                    outerRadius={100}
                                    paddingAngle={5}
                                    dataKey="value"
                                >
                                    {summary.categoryDistribution.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={entry.color} stroke="none" />
                                    ))}
                                </Pie>
                                <Tooltip
                                    formatter={(value: number) => formatCurrency(value)}
                                    contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                                />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="mt-4 flex-1 flex flex-col justify-end">
                        <div className="grid grid-cols-2 gap-2">
                            {summary.categoryDistribution.map((item, idx) => (
                                <div key={idx} className="flex items-center text-sm">
                                    <div className="w-3 h-3 rounded-full mr-2" style={{ backgroundColor: item.color }}></div>
                                    <span className="text-slate-600 flex-1 truncate">{item.name}</span>
                                    <span className="font-medium text-slate-900">
                                        {((item.value / summary.totalValue) * 100).toFixed(1)}%
                                    </span>
                                </div>
                            ))}
                        </div>

                        {summary.indexDistribution.length > 0 && summary.totalValue > 0 && (
                            <div className="mt-5 pt-4 border-t border-slate-100">
                                <h4 className="text-xs font-semibold text-slate-500 mb-3">
                                    지수별 비중
                                </h4>
                                <div className="space-y-2">
                                    {summary.indexDistribution.map((item, idx) => (
                                        <div key={idx} className="flex items-center text-xs">
                                            <div
                                                className="w-2.5 h-2.5 rounded-full mr-2"
                                                style={{ backgroundColor: item.color }}
                                            />
                                            <span className="text-slate-600 flex-1 truncate">
                                                {item.name}
                                            </span>
                                            <span className="font-medium text-slate-900">
                                                {((item.value / summary.totalValue) * 100).toFixed(1)}%
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* History Chart */}
                <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 flex flex-col h-full">
                    <h3 className="text-lg font-bold text-slate-800 mb-6">자산 추이 (1년)</h3>
                    <div className="h-[350px] w-full flex items-center justify-center shrink-0">
                        {summary.historyData.length > 0 ? (
                            <ResponsiveContainer width="100%" height="100%" minHeight={300} minWidth={0}>
                                <AreaChart data={summary.historyData}>
                                    <defs>
                                        <linearGradient id="colorStocks" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#2563eb" stopOpacity={0.2} />
                                            <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                                        </linearGradient>
                                        <linearGradient id="colorRealEstate" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.2} />
                                            <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                                        </linearGradient>
                                    </defs>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                    <XAxis
                                        dataKey="date"
                                        axisLine={false}
                                        tickLine={false}
                                        tick={{ fill: '#94a3b8', fontSize: 12 }}
                                        dy={10}
                                    />
                                    <YAxis
                                        hide={true}
                                        domain={['dataMin', 'dataMax']}
                                    />
                                    <Tooltip
                                        formatter={(value: number) => formatCurrency(value)}
                                        labelStyle={{ color: '#64748b' }}
                                        contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                                    />
                                    <Legend verticalAlign="top" height={24} wrapperStyle={{ fontSize: '12px', color: '#64748b' }} />
                                    <Area
                                        type="monotone"
                                        dataKey="stockValue"
                                        name="주식"
                                        stroke="#2563eb"
                                        strokeWidth={3}
                                        fillOpacity={1}
                                        fill="url(#colorStocks)"
                                    />
                                    {showRealEstate && (
                                        <Area
                                            type="monotone"
                                            dataKey="realEstateValue"
                                            name="부동산(내 지분)"
                                            stroke="#f59e0b"
                                            strokeWidth={2}
                                            fillOpacity={1}
                                            fill="url(#colorRealEstate)"
                                        />
                                    )}
                                </AreaChart>
                            </ResponsiveContainer>
                        ) : (
                            <div className="text-slate-400 text-sm">
                                아직 자산 추이 데이터가 충분하지 않습니다.
                            </div>
                        )}
                    </div>

                    {historyStats && (
                        <div className="mt-4 pt-4 border-t border-slate-100">
                            <div className="text-[11px] text-slate-400 mb-3">주식 기준</div>
                            <div className="grid grid-cols-3 gap-y-4 gap-x-6">
                                <div>
                                    <span className="text-xs text-slate-500 block mb-1">총 원금</span>
                                    <span className="text-sm font-semibold text-slate-700">{formatCurrency(actualInvested ?? summary.totalInvested)}</span>
                                </div>
                                <div>
                                    <span className="text-xs text-slate-500 block mb-1">데이터 시작점</span>
                                    <span className="text-sm font-semibold text-slate-700">{formatCurrency(historyStats.start)}</span>
                                </div>
                                <div>
                                    <span className="text-xs text-slate-500 block mb-1">현재 금액</span>
                                    <span className="text-sm font-semibold text-slate-700">{formatCurrency(historyStats.end)}</span>
                                </div>
                                <div>
                                    <span className="text-xs text-slate-500 block mb-1">최고 금액</span>
                                    <span className="text-sm font-semibold text-slate-700">{formatCurrency(historyStats.max)}</span>
                                </div>
                                <div>
                                    <span className="text-xs text-slate-500 block mb-1">최저 금액</span>
                                    <span className="text-sm font-semibold text-slate-700">{formatCurrency(historyStats.min)}</span>
                                </div>
                                <div>
                                    <span className="text-xs text-slate-500 block mb-1">기간 변동</span>
                                    <div className={`flex items-center gap-1 text-sm font-bold ${historyStats.change >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                                        {historyStats.changeRate >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                                        {historyStats.changeRate > 0 ? '+' : ''}{historyStats.changeRate.toFixed(2)}%
                                    </div>
                                </div>
                                {benchmarkDiff !== null && (
                                    <div className="col-span-3 mt-2 pt-3 border-t border-slate-100">
                                        <div className="flex items-center justify-between">
                                            <div>
                                                <span className="text-xs text-slate-500 block mb-1">{benchmarkLabel}</span>
                                                <span className="text-[11px] text-slate-400">
                                                    시장지수 수익률 {benchmarkReturn?.toFixed(2)}%
                                                </span>
                                            </div>
                                            <div className={`flex items-center gap-1 text-sm font-bold ${benchmarkDiff >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                                                {benchmarkDiff >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                                                {benchmarkDiff > 0 ? '+' : ''}{benchmarkDiff.toFixed(2)}%p
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Yearly Stats Chart */}
            {yearlyStats && yearlyStats.length > 0 && (
                <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                    <h3 className="text-lg font-bold text-slate-800 mb-6">연도별 자산 흐름</h3>
                    <div className="h-[300px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={yearlyStats} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                                <XAxis
                                    dataKey="year"
                                    axisLine={false}
                                    tickLine={false}
                                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                                    dy={10}
                                />
                                <YAxis
                                    axisLine={false}
                                    tickLine={false}
                                    tick={{ fill: '#94a3b8', fontSize: 12 }}
                                    tickFormatter={(value) => `${(value / 1000000).toFixed(0)}M`}
                                />
                                <Tooltip
                                    cursor={{ fill: '#f8fafc' }}
                                    content={({ active, payload, label }) => {
                                        if (active && payload && payload.length) {
                                            const data = payload[0].payload;
                                            return (
                                                <div className="bg-white p-4 border border-slate-100 shadow-md rounded-xl text-sm min-w-[150px]">
                                                    <p className="font-bold text-slate-800 mb-2">{label}년</p>
                                                    {payload.map((entry: any, index: number) => (
                                                        <div key={index} className="flex items-center gap-2 mb-1 justify-between">
                                                            <div className="flex items-center gap-2">
                                                                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
                                                                <span className="text-slate-500">{entry.name}</span>
                                                            </div>
                                                            <span className="font-semibold ml-4">{formatCurrency(entry.value)}</span>
                                                        </div>
                                                    ))}
                                                    {data.note && (
                                                        <div className="mt-2 pt-2 border-t border-slate-100 text-xs text-slate-500 break-keep">
                                                            💡 {data.note}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        }
                                        return null;
                                    }}
                                />
                                <Legend wrapperStyle={{ position: 'relative', marginTop: '10px' }} />
                                <Bar dataKey="deposit" name="입금" fill="#818cf8" radius={[4, 4, 0, 0]} />
                                <Bar dataKey="withdrawal" name="출금" fill="#fda4af" radius={[4, 4, 0, 0]} />
                                <Bar dataKey="net" name="순입금" fill="#34d399" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}
        </div>
    );
};
