import React, { useMemo } from 'react';
import { Asset, AssetCategory, PortfolioSummary, TargetIndexAllocation, DividendEntry } from '../types';
import { formatCurrency, COLORS, MOCK_HISTORY_DATA } from '../constants';
import { PieChart, Pie, Cell, ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { TrendingUp, Wallet, PieChart as PieIcon, ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface DashboardProps {
  assets: Asset[];
  targetIndexAllocations?: TargetIndexAllocation[];
  historyData?: { date: string; value: number }[];
  dividendTotalYear?: number;
  dividendYear?: number;
  dividends?: DividendEntry[];
}

export const Dashboard: React.FC<DashboardProps> = ({
  assets,
  targetIndexAllocations,
  historyData,
  dividendTotalYear,
  dividendYear,
  dividends,
}) => {
  const summary: PortfolioSummary = useMemo(() => {
    let totalValue = 0;
    let totalInvested = 0;
    let realizedProfitTotal = 0;
    const catMap = new Map<string, number>();
    const indexMap = new Map<string, number>();

    assets.forEach(asset => {
      const val = asset.amount * asset.currentPrice;
      const invested = asset.amount * (asset.purchasePrice || asset.currentPrice);
      const realized = asset.realizedProfit || 0;

      totalValue += val;
      totalInvested += invested;
      realizedProfitTotal += realized;

      const currentCatVal = catMap.get(asset.category) || 0;
      catMap.set(asset.category, currentCatVal + val);

      if (asset.indexGroup) {
        const currentIndexVal = indexMap.get(asset.indexGroup) || 0;
        indexMap.set(asset.indexGroup, currentIndexVal + val);
      }
    });

    const unrealizedProfitTotal = totalValue - totalInvested;

    const categoryDistribution = Array.from(catMap.entries()).map(([name, value], index) => ({
      name,
      value,
      color: COLORS[index % COLORS.length]
    })).sort((a, b) => b.value - a.value);

    const indexDistribution = Array.from(indexMap.entries()).map(([name, value], index) => ({
      name,
      value,
      color: COLORS[index % COLORS.length]
    })).sort((a, b) => b.value - a.value);

    const history = historyData || [];

    return {
      totalValue,
      totalInvested,
      realizedProfitTotal,
      unrealizedProfitTotal,
      categoryDistribution,
      indexDistribution,
      historyData: history,
    };
  }, [assets, historyData]);

  const totalProfit = summary.realizedProfitTotal + summary.unrealizedProfitTotal;
  const profitRate = summary.totalInvested > 0 ? (totalProfit / summary.totalInvested) * 100 : 0;
  const isPositive = totalProfit >= 0;

  const dividendInfo = useMemo(() => {
    const list: DividendEntry[] = (dividends || []).filter(
      (d) => typeof d.year === 'number' && typeof d.total === 'number' && d.total > 0,
    );

    if (list.length > 0) {
      const sorted = [...list].sort((a, b) => b.year - a.year);
      const targetYear = dividendYear ?? sorted[0].year;
      const main =
        sorted.find((d) => d.year === targetYear) ??
        sorted[0];
      return {
        mainYear: main.year,
        mainTotal: main.total,
        list: sorted,
      };
    }

    if (typeof dividendTotalYear === 'number' && dividendTotalYear > 0) {
      const year = dividendYear || new Date().getFullYear();
      return {
        mainYear: year,
        mainTotal: dividendTotalYear,
        list: [{ year, total: dividendTotalYear }],
      };
    }

    return null;
  }, [dividends, dividendTotalYear, dividendYear]);

  const fxInfo = useMemo(() => {
    const usdAssetsValue = assets
      .filter((asset) => asset.category === AssetCategory.STOCK_US)
      .reduce((sum, asset) => sum + asset.amount * asset.currentPrice, 0);

    // 환율 값은 SettingsPanel/App에서 관리되며, AppSettings를 통해 전달된다.
    // localStorage에는 전체 settings가 저장되므로, 여기서는 간단히 읽어서 사용한다.
    if (typeof window === 'undefined') {
      return {
        enabled: false,
        usdAssetsValue: 0,
        fxPnl: 0,
        fxRateChange: 0,
        usdFxBase: 0,
        usdFxNow: 0,
      };
    }

    let usdFxBase = 0;
    let usdFxNow = 0;
    try {
      const raw = window.localStorage.getItem('myportfolio_settings');
      if (raw) {
        const parsed = JSON.parse(raw) as { usdFxBase?: number; usdFxNow?: number } | null;
        if (parsed && typeof parsed === 'object') {
          usdFxBase = typeof parsed.usdFxBase === 'number' ? parsed.usdFxBase : 0;
          usdFxNow = typeof parsed.usdFxNow === 'number' ? parsed.usdFxNow : 0;
        }
      }
    } catch {
      // ignore
    }

    const enabled = usdAssetsValue > 0 && usdFxBase > 0 && usdFxNow > 0;
    if (!enabled) {
      return {
        enabled: false,
        usdAssetsValue,
        fxPnl: 0,
        fxRateChange: 0,
        usdFxBase,
        usdFxNow,
      };
    }

    const fxPnl = (usdAssetsValue * (usdFxNow - usdFxBase)) / usdFxNow;
    const fxRateChange = (usdFxNow / usdFxBase - 1) * 100;

    return {
      enabled: true,
      usdAssetsValue,
      fxPnl,
      fxRateChange,
      usdFxBase,
      usdFxNow,
    };
  }, [assets]);

  const rebalanceNotices: string[] = useMemo(() => {
    if (!targetIndexAllocations || targetIndexAllocations.length === 0) return [];
    if (summary.totalValue <= 0 || summary.indexDistribution.length === 0) return [];

    const positiveTargets = targetIndexAllocations.filter(a => a.targetWeight > 0 && a.indexGroup.trim());
    if (positiveTargets.length === 0) return [];

    const totalTargetWeight = positiveTargets.reduce((sum, a) => sum + a.targetWeight, 0);
    if (totalTargetWeight <= 0) return [];

    const targetShareMap = new Map<string, number>();
    positiveTargets.forEach(a => {
      targetShareMap.set(a.indexGroup.trim(), a.targetWeight / totalTargetWeight);
    });

    const actualShareMap = new Map<string, number>();
    summary.indexDistribution.forEach(item => {
      actualShareMap.set(item.name, item.value / summary.totalValue);
    });

    const threshold = 0.05; // 5%p 이상 차이 나면 알림
    const messages: string[] = [];

    targetShareMap.forEach((targetShare, name) => {
      const actualShare = actualShareMap.get(name) ?? 0;
      const diff = actualShare - targetShare;
      if (Math.abs(diff) >= threshold) {
        const diffPercent = Math.abs(diff * 100).toFixed(1);
        const direction = diff > 0 ? '높습니다' : '낮습니다';
        messages.push(`${name} 비중이 목표 대비 약 ${diffPercent}%p ${direction}.`);
      }
    });

    return messages;
  }, [summary.totalValue, summary.indexDistribution, targetIndexAllocations]);

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
              {isPositive ? <ArrowUpRight size={16} className="mr-1" /> : <ArrowDownRight size={16} className="mr-1" />}
              {Math.abs(profitRate).toFixed(2)}%
            </span>
            <span className="text-slate-400 ml-2">수익률</span>
          </div>
          {fxInfo.enabled && (
            <div className="mt-2 text-xs text-slate-500">
              추정 환차{fxInfo.fxPnl >= 0 ? '익' : '손'} (USD 자산 기준){' '}
              <span
                className={`font-semibold ${
                  fxInfo.fxPnl > 0 ? 'text-red-500' : fxInfo.fxPnl < 0 ? 'text-blue-500' : 'text-slate-500'
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

        <div className="bg-white p-6 rounded-2xl shadow-sm border border-slate-100">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-sm font-medium text-slate-500 mb-1">손익 (실현 + 평가)</p>
              <h2 className={`text-2xl md:text-3xl font-bold ${isPositive ? 'text-slate-900' : 'text-red-600'}`}>
                {isPositive ? '+' : ''}{formatCurrency(totalProfit)}
              </h2>
            </div>
            <div className="p-2 bg-green-50 rounded-lg text-green-600">
              <TrendingUp size={24} />
            </div>
          </div>
          <div className="mt-4 text-sm text-slate-400">
            총 투자 원금: {formatCurrency(summary.totalInvested)}
          </div>
          <div className="mt-1 text-xs text-slate-500">
            실현손익:{' '}
            <span className={summary.realizedProfitTotal >= 0 ? 'text-red-500 font-semibold' : 'text-blue-500 font-semibold'}>
              {summary.realizedProfitTotal > 0 ? '+' : summary.realizedProfitTotal < 0 ? '-' : ''}
              {formatCurrency(Math.abs(summary.realizedProfitTotal))}
            </span>{' '}
            / 평가손익:{' '}
            <span className={summary.unrealizedProfitTotal >= 0 ? 'text-red-500 font-semibold' : 'text-blue-500 font-semibold'}>
              {summary.unrealizedProfitTotal > 0 ? '+' : summary.unrealizedProfitTotal < 0 ? '-' : ''}
              {formatCurrency(Math.abs(summary.unrealizedProfitTotal))}
            </span>
          </div>
          {dividendInfo && (
            <div className="mt-1 text-xs text-slate-500">
              {dividendInfo.mainYear}년 배당금(수동 입력):{' '}
              <span className="font-semibold text-emerald-600">
                +{formatCurrency(dividendInfo.mainTotal)}
              </span>
            </div>
          )}
          {dividendInfo && dividendInfo.list.length > 1 && (
            <div className="mt-1 text-[11px] text-slate-400 space-x-2">
              {dividendInfo.list.map((d) => (
                <span key={d.year}>
                  {d.year}: +{formatCurrency(d.total)}
                </span>
              ))}
            </div>
          )}
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
    </div>
  );
};
