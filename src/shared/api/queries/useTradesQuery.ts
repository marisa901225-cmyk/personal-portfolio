/**
 * Trades Query Hook
 * 
 * 거래 내역을 가져오는 React Query 훅
 */

import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { ApiClient, BackendTrade, mapBackendTradesToFrontend } from '@lib/api';
import { Asset, TradeRecord } from '@lib/types';
import { queryKeys } from '../queryKeys';

interface TradesQueryParams {
    limit?: number;
    beforeId?: number;
    assetId?: number;
}

/**
 * 거래 내역 조회 (원본 백엔드 형식)
 */
export function useTradesRawQuery(
    apiClient: ApiClient | null,
    params?: TradesQueryParams,
    options?: Omit<UseQueryOptions<BackendTrade[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: params?.assetId
            ? queryKeys.tradesForAsset(params.assetId)
            : queryKeys.trades,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchTrades(params);
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 1, // 1분
        ...options,
    });
}

/**
 * 거래 내역 조회 (프론트엔드 형식으로 변환)
 * 
 * @param assets - 자산 목록 (거래에 자산명을 매핑하기 위해 필요)
 */
export function useTradesQuery(
    apiClient: ApiClient | null,
    assets: Asset[],
    params?: TradesQueryParams,
    options?: Omit<UseQueryOptions<TradeRecord[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: params?.assetId
            ? queryKeys.tradesForAsset(params.assetId)
            : queryKeys.trades,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            const trades = await apiClient.fetchTrades(params);
            return mapBackendTradesToFrontend(trades, assets);
        },
        enabled: !!apiClient && assets.length > 0,
        staleTime: 1000 * 60 * 1,
        ...options,
    });
}
