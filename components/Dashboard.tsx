import React, { useMemo } from 'react';
import { Asset, PortfolioSummary } from '../types';
import { formatCurrency, COLORS, MOCK_HISTORY_DATA } from '../constants';
import { PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { TrendingUp, Wallet, PieChart as PieIcon, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface DashboardProps {
  assets: Asset[];
}

export const Dashboard: React.FC<DashboardProps> = ({ assets }) => {
  const summary: PortfolioSummary = useMemo(() => {
    let totalValue = 0;
    let totalInvested = 0;
    const catMap = new Map<string, number>();

    assets.forEach(asset => {
      const val = asset.amount * asset.currentPrice;
      const invested = asset.amount * (asset.purchasePrice || asset.currentPrice);
      
      totalValue += val;
      totalInvested += invested;

      const currentCatVal = catMap.get(asset.category) || 0;
      catMap.set(asset.category, currentCatVal + val);
    });

    const categoryDistribution = Array.from(catMap.entries()).map(([name, value], index) => ({
      name,
      value,
      color: COLORS[index % COLORS.length]
    })).sort((a, b) => b.value - a.value);

    return {
      totalValue,
      totalInvested,
      categoryDistribution,
      historyData: MOCK_HISTORY_DATA // In a real app, this would be derived from historical snapshots
    };
  }, [assets]);

  const profit = summary.totalValue - summary.totalInvested;
  const profitRate = summary.totalInvested > 0 ? (profit / summary.totalInvested) * 100 : 0;
  const isPositive = profit >= 0;

  return (
    <div className="space-y-6 pb-20 md:pb-0 animate-fade-in">
      {/* Top Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100 relative overflow-hidden">
          <div className="flex justify-between items-start z-10 relative">
            <div>
              <p className="text-sm font-medium text-slate-500 mb-1">총 자산</p>
              <h2 className="text-2xl md:text-3xl font-bold text-slate-900">{formatCurrency(summary.totalValue)}</h2>
            </div>
            <div className="p-2 bg-indigo-50 rounded-lg text-indigo-600">
              <Wallet size={24} />
            </div>
          </div>
          <div className="mt-4 flex items-center text-sm">
             <span className={`flex items-center font-semibold ${isPositive ? 'text-green-600' : 'text-red-600'}`}>
                {isPositive ? <ArrowUpRight size={16} className="mr-1"/> : <ArrowDownRight size={16} className="mr-1"/>}
                {Math.abs(profitRate).toFixed(2)}%
             </span>
             <span className="text-slate-400 ml-2">수익률</span>
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-sm font-medium text-slate-500 mb-1">평가 손익</p>
              <h2 className={`text-2xl md:text-3xl font-bold ${isPositive ? 'text-slate-900' : 'text-red-600'}`}>
                {isPositive ? '+' : ''}{formatCurrency(profit)}
              </h2>
            </div>
            <div className="p-2 bg-green-50 rounded-lg text-green-600">
              <TrendingUp size={24} />
            </div>
          </div>
          <div className="mt-4 text-sm text-slate-400">
            총 투자 원금: {formatCurrency(summary.totalInvested)}
          </div>
        </div>

        <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
            <div className="flex justify-between items-start">
            <div>
              <p className="text-sm font-medium text-slate-500 mb-1">자산 구성</p>
              <h2 className="text-2xl font-bold text-slate-900">
                {summary.categoryDistribution.length}개 카테고리
              </h2>
            </div>
            <div className="p-2 bg-purple-50 rounded-lg text-purple-600">
              <PieIcon size={24} />
            </div>
          </div>
           <div className="mt-4 text-sm text-slate-400">
            가장 큰 비중: <span className="font-medium text-slate-700">{summary.categoryDistribution[0]?.name || '-'}</span>
          </div>
        </div>
      </div>

      {/* Charts Section */}
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
        </div>

        {/* History Chart */}
        <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
          <h3 className="text-lg font-bold text-slate-800 mb-6">자산 추이 (6개월)</h3>
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={summary.historyData}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis 
                    dataKey="date" 
                    axisLine={false} 
                    tickLine={false} 
                    tick={{fill: '#94a3b8', fontSize: 12}} 
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
          </div>
        </div>
      </div>
    </div>
  );
};