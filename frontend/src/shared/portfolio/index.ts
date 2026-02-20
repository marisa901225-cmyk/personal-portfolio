/**
 * 포트폴리오 도메인 유틸리티 통합
 * 
 * lib/utils/constants.ts + cmaConfig.ts + tickerUtils.ts + hooks/portfolioTypes.ts 통합
 */

import { AssetCategory } from '@lib/types';

// ==================== 타입 ====================

export const CATEGORY_LABELS: Record<AssetCategory, string> = {
    [AssetCategory.CASH]: '현금/CMA',
    [AssetCategory.STOCK_KR]: '국내주식',
    [AssetCategory.STOCK_US]: '해외주식',
    [AssetCategory.CRYPTO]: '가상자산',
    [AssetCategory.PENSION]: '연금/IRP',
    [AssetCategory.REAL_ESTATE]: '부동산',
    [AssetCategory.GOLD]: '금/원자재',
    [AssetCategory.LOAN]: '부채',
    [AssetCategory.OTHER]: '기타',
};

export const getCategoryLabel = (category: string | AssetCategory): string => {
    return CATEGORY_LABELS[category as AssetCategory] || category;
};

export interface CmaConfig {
    /** 기준 잔액 (KRW) */
    principal: number;
    /** 연 이자율 (세전, %) */
    annualRate: number;
    /** 이자소득세율 (%, 기본 15.4) */
    taxRate: number;
    /** 이자 계산 시작일 (YYYY-MM-DD) */
    startDate: string;
}

export interface ImportedAssetSnapshot {
    name: string;
    ticker?: string;
    category: AssetCategory;
    amount: number;
    purchasePrice?: number;
    currentPrice: number;
    realizedProfit?: number;
    currency: 'KRW' | 'USD';
}

// ==================== 상수 ====================

export const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f43f5e', '#10b981', '#3b82f6'];
export const MOCK_HISTORY_DATA: { date: string; value: number }[] = [];

export const REAL_ESTATE_TOTAL_PURCHASE = 145000000;
export const REAL_ESTATE_MY_SHARE = 53750000;
export const REAL_ESTATE_SHARE_RATIO = REAL_ESTATE_MY_SHARE / REAL_ESTATE_TOTAL_PURCHASE;

// ==================== 포맷팅 함수 ====================

export const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('ko-KR', {
        style: 'currency',
        currency: 'KRW',
        maximumFractionDigits: 0
    }).format(value);
};

export const formatCompactNumber = (number: number) => {
    const formatter = Intl.NumberFormat("ko-KR", { notation: "compact" });
    return formatter.format(number);
};

// ==================== CMA 계산 ====================

/** 세후 단순 이자 계산 (일 단위, 단리) */
export const calculateCmaBalance = (config: CmaConfig, asOf: Date = new Date()): number => {
    const start = new Date(config.startDate);
    const startDay = new Date(start.getFullYear(), start.getMonth(), start.getDate());
    const endDay = new Date(asOf.getFullYear(), asOf.getMonth(), asOf.getDate());

    const msPerDay = 1000 * 60 * 60 * 24;
    const days = Math.max(0, Math.floor((endDay.getTime() - startDay.getTime()) / msPerDay));

    if (config.principal <= 0 || config.annualRate <= 0 || days <= 0) {
        return Math.round(config.principal);
    }

    const grossRate = config.annualRate / 100;
    const taxRate = config.taxRate / 100;
    const netRate = grossRate * (1 - taxRate);
    const interest = config.principal * netRate * (days / 365);
    const balance = config.principal + interest;

    return Math.round(balance);
};

// ==================== 티커 유틸 ====================

const FOREIGN_EXCHANGE_PREFIXES = ['NAS:', 'NYS:', 'AMS:', 'HKS:', 'SHS:', 'SZS:', 'TSE:', 'LON:'];

/**
 * 티커 문자열을 보고 자산 카테고리를 추론합니다.
 */
export function inferCategoryFromTicker(
    ticker: string | undefined,
    currentCategory: AssetCategory
): AssetCategory {
    if (!ticker || ticker.trim() === '') {
        return currentCategory;
    }

    const upperTicker = ticker.toUpperCase().trim();

    for (const prefix of FOREIGN_EXCHANGE_PREFIXES) {
        if (upperTicker.startsWith(prefix)) {
            return AssetCategory.STOCK_US;
        }
    }

    if (/^\d{6}$/.test(upperTicker)) {
        return AssetCategory.STOCK_KR;
    }

    return currentCategory;
}
