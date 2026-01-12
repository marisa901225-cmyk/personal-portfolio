import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { ApiClient } from '../client';
import { BackendNewsSearchResponse } from '../client/types';

/**
 * 관련 뉴스 검색 훅
 */
export const useNewsQuery = (
    apiClient: ApiClient | null,
    query: string,
    options?: Omit<UseQueryOptions<BackendNewsSearchResponse, Error>, 'queryKey' | 'queryFn'> & { ticker?: string | null }
) => {
    return useQuery<BackendNewsSearchResponse, Error>({
        queryKey: ['news', { query, ticker: options?.ticker }],
        queryFn: async () => {
            if (!apiClient) throw new Error('ApiClient is not initialized');
            return apiClient.searchNews(query, options?.ticker ?? undefined);
        },
        enabled: Boolean(apiClient && query),
        staleTime: 1000 * 60 * 5, // 5분 캐시
        ...options,
    });
};
