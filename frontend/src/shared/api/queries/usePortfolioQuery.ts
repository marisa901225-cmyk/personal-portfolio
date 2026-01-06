/**
 * Portfolio Query Hooks
 * 
 * 포트폴리오 데이터를 가져오는 React Query 훅들
 */

import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { ApiClient, BackendPortfolioResponse, mapBackendAssetToFrontend } from '@lib/api';
import { Asset } from '@lib/types';
import { queryKeys } from '../queryKeys';

/**
 * 전체 포트폴리오 데이터 조회 (자산 + 거래 + 요약)
 */
export function usePortfolioQuery(
    apiClient: ApiClient | null,
    options?: Omit<UseQueryOptions<BackendPortfolioResponse, Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.portfolio,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchPortfolio();
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 2, // 2분
        ...options,
    });
}

/**
 * 자산 목록만 조회 (Portfolio에서 추출)
 */
export function useAssetsQuery(
    apiClient: ApiClient | null,
    options?: Omit<
        UseQueryOptions<BackendPortfolioResponse, Error, Asset[]>,
        'queryKey' | 'queryFn' | 'select'
    >
) {
    return useQuery({
        queryKey: queryKeys.portfolio,
        queryFn: async (): Promise<BackendPortfolioResponse> => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchPortfolio();
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 2,
        select: (data) => data.assets.map(mapBackendAssetToFrontend),
        ...options,
    });
}

/**
 * 포트폴리오 요약 정보만 조회
 */
export function usePortfolioSummaryQuery(
    apiClient: ApiClient | null,
) {
    return useQuery({
        queryKey: queryKeys.portfolio,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchPortfolio();
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 2,
        select: (data) => data.summary,
    });
}
