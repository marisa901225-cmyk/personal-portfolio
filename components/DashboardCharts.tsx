import React from 'react';
import { PortfolioSummary } from '../types';
import { formatCurrency } from '../constants';
import { PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';

interface DashboardChartsProps {
    summary: PortfolioSummary;
    rebalanceNotices: string[];
}

export const DashboardCharts: React.FC<DashboardChartsProps> = ({
    summary,
    rebalanceNotices,
}) => {
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

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Allocation Chart */}
                <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                    <h3 className="text-lg font-bold text-slate-800 mb-6">포트폴리오 비중</h3>
                    <div className="h-[300px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
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
                    <div className="grid grid-cols-2 gap-2 mt-4">
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

                {/* History Chart */}
                <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
                    <h3 className="text-lg font-bold text-slate-800 mb-6">자산 추이 (6개월)</h3>
                    <div className="h-[300px] w-full flex items-center justify-center">
                        {summary.historyData.length > 0 ? (
                            <ResponsiveContainer width="100%" height="100%">
                                <AreaChart data={summary.historyData}>
                                    <defs>
                                        <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                                            <stop offset="5%" stopColor="#6366f1" stopOpacity={0.2} />
                                            <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
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
                                    <Area
                                        type="monotone"
                                        dataKey="value"
                                        stroke="#6366f1"
                                        strokeWidth={3}
                                        fillOpacity={1}
                                        fill="url(#colorValue)"
                                    />
                                </AreaChart>
                            </ResponsiveContainer>
                        ) : (
                            <div className="text-slate-400 text-sm">
                                아직 자산 추이 데이터가 충분하지 않습니다.
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};
