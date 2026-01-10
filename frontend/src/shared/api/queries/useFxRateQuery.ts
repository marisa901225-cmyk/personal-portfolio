/**
 * FX Rate Query Hook
 * 
 * USD/KRW 환율을 가져오는 훅
 */

import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { ApiClient, BackendFxRateResponse } from '@/shared/api/client';
import { queryKeys } from '../queryKeys';

/**
 * USD/KRW 환율 조회
 */
export function useFxRateQuery(
    apiClient: ApiClient | null,
    options?: Omit<UseQueryOptions<BackendFxRateResponse, Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.fxRate,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchUsdKrwFxRate();
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 30, // 30분 (환율은 자주 변경되지 않음)
        gcTime: 1000 * 60 * 60, // 1시간
        retry: 1,
        ...options,
    });
}

/**
 * 환율 값만 추출
 */
export function useFxRateValue(apiClient: ApiClient | null) {
    const { data } = useFxRateQuery(apiClient);
    return data?.rate ?? null;
}
