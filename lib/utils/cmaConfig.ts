/**
 * 발행어음/CMA 세후 이자 계산 유틸리티
 */

export interface CmaConfig {
    /** 기준 잔액 (KRW, 세전/세후는 사용자가 선택적으로 관리) */
    principal: number;
    /** 연 이자율 (세전, %) */
    annualRate: number;
    /** 이자소득세율 (%, 기본 15.4) */
    taxRate: number;
    /** 이자 계산 시작일 (YYYY-MM-DD) */
    startDate: string;
}

/** 세후 단순 이자 계산 (일 단위, 단리) */
export const calculateCmaBalance = (config: CmaConfig, asOf: Date = new Date()): number => {
    const start = new Date(config.startDate);
    // 시간대/시각에 따른 미세 오차를 줄이기 위해 날짜만 기준으로 계산
    const startDay = new Date(start.getFullYear(), start.getMonth(), start.getDate());
    const endDay = new Date(asOf.getFullYear(), asOf.getMonth(), asOf.getDate());

    const msPerDay = 1000 * 60 * 60 * 24;
    const days = Math.max(0, Math.floor((endDay.getTime() - startDay.getTime()) / msPerDay));

    if (config.principal <= 0 || config.annualRate <= 0 || days <= 0) {
        return Math.round(config.principal);
    }

    const grossRate = config.annualRate / 100; // 세전 연 이율
    const taxRate = config.taxRate / 100; // 이자소득세율
    const netRate = grossRate * (1 - taxRate); // 세후 연 이율

    // 단리: 이자 = 원금 * 세후연이율 * (일수 / 365)
    const interest = config.principal * netRate * (days / 365);
    const balance = config.principal + interest;

    // 원 단위 반올림
    return Math.round(balance);
};
