import { useMemo } from 'react';
import { PortfolioSummary, AssetCategory } from '../../lib/types';

interface UsePortfolioCalculationsProps {
    summary: PortfolioSummary;
    actualInvested?: number;
    realEstateSummary?: {
        totalValue: number;
        totalInvested: number;
    };
    benchmarkReturn?: number;
}

export const usePortfolioCalculations = ({
    summary,
    actualInvested,
    realEstateSummary,
    benchmarkReturn,
}: UsePortfolioCalculationsProps) => {
    // 1. 수익률 및 이익 관련 계산
    const profitStats = useMemo(() => {
        const invested = actualInvested ?? summary.totalInvested;
        const totalProfit = summary.totalValue - invested;
        const profitRate = invested > 0 ? (totalProfit / invested) * 100 : 0;
        return {
            totalProfit,
            profitRate,
            isPositive: totalProfit >= 0,
            invested
        };
    }, [summary.totalValue, summary.totalInvested, actualInvested]);

    // 2. 히스토리 데이터 통계
    const historyStats = useMemo(() => {
        if (!summary.historyData || summary.historyData.length === 0) return null;

        const data = summary.historyData;
        const getValue = (item: typeof data[number]) =>
            typeof item.stockValue === 'number'
                ? item.stockValue + (item.realEstateValue ?? 0)
                : item.value;

        const start = getValue(data[0]);
        const end = getValue(data[data.length - 1]);
        const values = data.map(d => getValue(d));

        const max = Math.max(...values);
        const min = Math.min(...values);
        const change = end - start;
        const changeRate = start !== 0 ? (change / start) * 100 : 0;

        return { start, end, max, min, change, changeRate };
    }, [summary.historyData]);

    // 3. 자산 비중 상세 계산 (부동산 분리형)
    const distributionDetails = useMemo(() => {
        const grandTotal = summary.totalValue;
        const realEstateValue = realEstateSummary?.totalValue ?? 0;
        const investableTotal = grandTotal - realEstateValue;

        const categories = summary.categoryDistribution.map(item => {
            if (item.name === '부동산' && realEstateSummary) {
                return { ...item, value: realEstateSummary.totalValue };
            }
            return item;
        });

        const indices = summary.indexDistribution || [];

        return { categories, indices, grandTotal, investableTotal };
    }, [summary.totalValue, summary.categoryDistribution, summary.indexDistribution, realEstateSummary]);

    // 4. 벤치마크 비교
    const benchmarkDiff = useMemo(() => {
        if (!historyStats || benchmarkReturn === undefined || !Number.isFinite(benchmarkReturn)) {
            return null;
        }

        const baseReturn = (summary.xirr_rate !== undefined && summary.xirr_rate !== null)
            ? summary.xirr_rate * 100
            : historyStats.changeRate;

        return baseReturn - benchmarkReturn;
    }, [historyStats, benchmarkReturn, summary.xirr_rate]);

    return {
        profitStats,
        historyStats,
        distributionDetails,
        benchmarkDiff,
        showRealEstate: summary.historyData.some(item => (item.realEstateValue ?? 0) > 0),
    };
};
