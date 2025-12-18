import React, { useMemo } from 'react';
import { Asset, AssetCategory, PortfolioSummary, TargetIndexAllocation, DividendEntry } from '../types';
import { COLORS } from '../constants';
import { DashboardSummary } from './DashboardSummary';
import { DashboardCharts } from './DashboardCharts';
import type { BackendPortfolioSummary } from '../backendClient';

const normalizeIndexKey = (name: string): string =>
  name.replace(/\s+/g, '').toUpperCase();

interface DashboardProps {
  assets: Asset[];
  backendSummary?: BackendPortfolioSummary;
  targetIndexAllocations?: TargetIndexAllocation[];
  historyData?: { date: string; value: number }[];
  dividendTotalYear?: number;
  dividendYear?: number;
  dividends?: DividendEntry[];
  onUpdateDividends?: () => void;
  usdFxBase?: number;
  usdFxNow?: number;
}

export const Dashboard: React.FC<DashboardProps> = ({
  assets,
  backendSummary,
  targetIndexAllocations,
  historyData,
  dividendTotalYear,
  dividendYear,
  dividends,
  onUpdateDividends,
  usdFxBase,
  usdFxNow,
}) => {
  const { summary, investableSummary, realEstate } = useMemo(() => {
    const history = historyData || [];

    // 투자 가능 자산(부동산 제외)과 부동산 요약은 여전히 프론트에서 계산하되,
    // 전체 포트폴리오 요약은 가능한 한 백엔드에서 전달된 summary를 사용한다.

    // Investable Assets (Excluding Real Estate)
    let invTotalValue = 0;
    let invTotalInvested = 0;
    let invRealizedProfitTotal = 0;
    const invCatMap = new Map<string, number>();
    const invIndexAgg = new Map<string, { name: string; value: number }>();

    // Real Estate Only
    let reValue = 0;
    let reInvested = 0;
    let reRealized = 0;

    assets.forEach(asset => {
      const val = asset.amount * asset.currentPrice;
      const invested = asset.amount * (asset.purchasePrice || asset.currentPrice);
      const realized = asset.realizedProfit || 0;

      // --- Investable vs Real Estate ---
      if (asset.category === AssetCategory.REAL_ESTATE) {
        reValue += val;
        reInvested += invested;
        reRealized += realized;
      } else {
        invTotalValue += val;
        invTotalInvested += invested;
        invRealizedProfitTotal += realized;

        const invCatVal = invCatMap.get(asset.category) || 0;
        invCatMap.set(asset.category, invCatVal + val);

        if (asset.indexGroup) {
          const key = normalizeIndexKey(asset.indexGroup);
          const existing = invIndexAgg.get(key);
          const label = existing?.name ?? asset.indexGroup;
          invIndexAgg.set(key, {
            name: label,
            value: (existing?.value ?? 0) + val,
          });
        }
      }
    });

    const invUnrealizedProfitTotal = invTotalValue - invTotalInvested;

    const invCategoryDistribution = Array.from(invCatMap.entries()).map(([name, value], index) => ({
      name,
      value,
      color: COLORS[index % COLORS.length]
    })).sort((a, b) => b.value - a.value);

    const invIndexDistribution = Array.from(invIndexAgg.values()).map((item, index) => ({
      name: item.name,
      value: item.value,
      color: COLORS[index % COLORS.length]
    })).sort((a, b) => b.value - a.value);

    const investableSummary: PortfolioSummary = {
      totalValue: invTotalValue,
      totalInvested: invTotalInvested,
      realizedProfitTotal: invRealizedProfitTotal,
      unrealizedProfitTotal: invUnrealizedProfitTotal,
      categoryDistribution: invCategoryDistribution,
      indexDistribution: invIndexDistribution,
      historyData: history,
    };

    const realEstate = {
      totalValue: reValue,
      totalInvested: reInvested,
      realizedProfitTotal: reRealized,
    };

    let summary: PortfolioSummary;

    if (backendSummary) {
      const categoryDistribution = backendSummary.category_distribution
        .map((item, index) => ({
          name: item.name,
          value: item.value,
          color: COLORS[index % COLORS.length],
        }))
        .sort((a, b) => b.value - a.value);

      const indexAgg = new Map<string, { name: string; value: number }>();
      backendSummary.index_distribution.forEach((item) => {
        const key = normalizeIndexKey(item.name);
        const existing = indexAgg.get(key);
        const label = existing?.name ?? item.name;
        indexAgg.set(key, {
          name: label,
          value: (existing?.value ?? 0) + item.value,
        });
      });

      const indexDistribution = Array.from(indexAgg.values())
        .map((item, index) => ({
          name: item.name,
          value: item.value,
          color: COLORS[index % COLORS.length],
        }))
        .sort((a, b) => b.value - a.value);

      summary = {
        totalValue: backendSummary.total_value,
        totalInvested: backendSummary.total_invested,
        realizedProfitTotal: backendSummary.realized_profit_total,
        unrealizedProfitTotal: backendSummary.unrealized_profit_total,
        categoryDistribution,
        indexDistribution,
        historyData: history,
      };
    } else {
      // 서버 summary가 없을 때는 기존과 동일하게 프론트에서 전체 요약을 계산
      let totalValue = 0;
      let totalInvested = 0;
      let realizedProfitTotal = 0;
      const catMap = new Map<string, number>();
      const indexAgg = new Map<string, { name: string; value: number }>();

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
          const key = normalizeIndexKey(asset.indexGroup);
          const existing = indexAgg.get(key);
          const label = existing?.name ?? asset.indexGroup;
          indexAgg.set(key, {
            name: label,
            value: (existing?.value ?? 0) + val,
          });
        }
      });

      const unrealizedProfitTotal = totalValue - totalInvested;

      const categoryDistribution = Array.from(catMap.entries()).map(([name, value], index) => ({
        name,
        value,
        color: COLORS[index % COLORS.length],
      })).sort((a, b) => b.value - a.value);

      const indexDistribution = Array.from(indexAgg.values()).map((item, index) => ({
        name: item.name,
        value: item.value,
        color: COLORS[index % COLORS.length],
      })).sort((a, b) => b.value - a.value);

      summary = {
        totalValue,
        totalInvested,
        realizedProfitTotal,
        unrealizedProfitTotal,
        categoryDistribution,
        indexDistribution,
        historyData: history,
      };
    }

    return {
      summary,
      investableSummary,
      realEstate,
    };
  }, [assets, backendSummary, historyData]);

  // 배당금 정보 계산
  const dividendInfo = useMemo(() => {
    const list: DividendEntry[] = (dividends || []).filter(
      (d) => typeof d.year === 'number' && typeof d.total === 'number' && d.total > 0,
    );

    // 구버전 데이터 호환 (dividendTotalYear만 있는 경우)
    if (list.length === 0 && typeof dividendTotalYear === 'number' && dividendTotalYear > 0) {
      const year = dividendYear || new Date().getFullYear();
      list.push({ year, total: dividendTotalYear });
    }

    const sorted = [...list].sort((a, b) => a.year - b.year); // 차트용 오름차순
    const totalAllTime = sorted.reduce((sum, d) => sum + d.total, 0);
    const currentYear = new Date().getFullYear();
    const currentYearTotal = sorted.find(d => d.year === currentYear)?.total || 0;

    return {
      list: sorted,
      totalAllTime,
      currentYearTotal,
      hasData: sorted.length > 0,
    };
  }, [dividends, dividendTotalYear, dividendYear]);

  // 총 손익 계산 (실현 + 평가 + 배당금)
  // 배당금은 재투자되어 원금(totalInvested)에 포함되므로, 수익으로 더해주지 않으면 수익률이 낮게 나옴.
  const totalProfit = summary.realizedProfitTotal + summary.unrealizedProfitTotal + dividendInfo.totalAllTime;
  const profitRate = summary.totalInvested > 0 ? (totalProfit / summary.totalInvested) * 100 : 0;
  const isPositive = totalProfit >= 0;

  const fxInfo = useMemo(() => {
    const usdAssetsValue = assets
      .filter((asset) => asset.category === AssetCategory.STOCK_US)
      .reduce((sum, asset) => sum + asset.amount * asset.currentPrice, 0);

    const base = typeof usdFxBase === 'number' ? usdFxBase : 0;
    const now = typeof usdFxNow === 'number' ? usdFxNow : 0;

    const enabled = usdAssetsValue > 0 && base > 0 && now > 0;
    if (!enabled) {
      return {
        enabled: false,
        usdAssetsValue,
        fxPnl: 0,
        fxRateChange: 0,
        usdFxBase: base,
        usdFxNow: now,
      };
    }

    const fxPnl = (usdAssetsValue * (now - base)) / now;
    const fxRateChange = (now / base - 1) * 100;

    return {
      enabled: true,
      usdAssetsValue,
      fxPnl,
      fxRateChange,
      usdFxBase: base,
      usdFxNow: now,
    };
  }, [assets, usdFxBase, usdFxNow]);

  const rebalanceNotices: string[] = useMemo(() => {
    if (!targetIndexAllocations || targetIndexAllocations.length === 0) return [];
    if (investableSummary.totalValue <= 0 || investableSummary.indexDistribution.length === 0) return [];

    const positiveTargets = targetIndexAllocations.filter(a => a.targetWeight > 0 && a.indexGroup.trim());
    if (positiveTargets.length === 0) return [];

    const totalTargetWeight = positiveTargets.reduce((sum, a) => sum + a.targetWeight, 0);
    if (totalTargetWeight <= 0) return [];

    // 합계가 100에 가깝고 각 값이 0~100이면 "퍼센트(%)"로 해석,
    // 그렇지 않으면 6/3/1처럼 상대 비중으로 해석하여 합계 기준으로 정규화.
    const isPercentMode =
      totalTargetWeight > 0 &&
      Math.abs(totalTargetWeight - 100) <= 1 &&
      positiveTargets.every(a => a.targetWeight >= 0 && a.targetWeight <= 100);

    const targetShareMap = new Map<string, { share: number; label: string }>();
    positiveTargets.forEach(a => {
      const weight = a.targetWeight;
      const share = isPercentMode ? weight / 100 : weight / totalTargetWeight;
      const key = normalizeIndexKey(a.indexGroup);
      const label = a.indexGroup.trim();
      targetShareMap.set(key, { share, label });
    });

    const actualShareMap = new Map<string, number>();
    investableSummary.indexDistribution.forEach(item => {
      const key = normalizeIndexKey(item.name);
      const prev = actualShareMap.get(key) ?? 0;
      actualShareMap.set(key, prev + item.value / investableSummary.totalValue);
    });

    const threshold = 0.05; // 5%p 이상 차이 나면 알림
    const messages: string[] = [];

    targetShareMap.forEach(({ share: targetShare, label }, key) => {
      const actualShare = actualShareMap.get(key) ?? 0;
      const diff = actualShare - targetShare;
      if (Math.abs(diff) >= threshold) {
        const diffPercent = Math.abs(diff * 100).toFixed(1);
        const direction = diff > 0 ? '높습니다' : '낮습니다';
        messages.push(`${label} 비중이 목표 대비 약 ${diffPercent}%p ${direction}.`);
      }
    });

    return messages;
  }, [investableSummary.totalValue, investableSummary.indexDistribution, targetIndexAllocations]);

  return (
    <div className="space-y-6 pb-20 md:pb-0 animate-fade-in">
      <DashboardSummary
        summary={summary}
        isPositive={isPositive}
        profitRate={profitRate}
        totalProfit={totalProfit}
        dividendInfo={dividendInfo}
        fxInfo={fxInfo}
        onUpdateDividends={onUpdateDividends}
        realEstateSummary={realEstate}
      />
      <DashboardCharts
        summary={investableSummary}
        rebalanceNotices={rebalanceNotices}
      />
    </div>
  );
};
