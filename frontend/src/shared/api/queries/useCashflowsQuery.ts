/**
 * Cashflows Query Hook
 * 
 * 연도별 입출금(Cashflow) 데이터를 가져오는 훅
 */

import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { ApiClient, BackendYearlyCashflow } from '@/shared/api/client';
import { queryKeys } from '../queryKeys';

export interface YearlyCashflowData {
    year: string;
    deposit: number;
    withdrawal: number;
    net: number;
    note?: string;
}

/**
 * 연도별 Cashflow 조회 (원본)
 */
export function useCashflowsRawQuery(
    apiClient: ApiClient | null,
    options?: Omit<UseQueryOptions<BackendYearlyCashflow[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.cashflows,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchCashflows();
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 10, // 10분
        ...options,
    });
}

/**
 * 연도별 Cashflow 조회 (프론트엔드 형식)
 */
export function useCashflowsQuery(
    apiClient: ApiClient | null,
    options?: Omit<UseQueryOptions<YearlyCashflowData[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.cashflows,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            const data = await apiClient.fetchCashflows();
            return data.map((cf) => ({
                year: cf.year.toString(),
                deposit: cf.deposit,
                withdrawal: cf.withdrawal,
                net: cf.net,
                note: cf.note ?? undefined,
            }));
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 10,
        ...options,
    });
}
