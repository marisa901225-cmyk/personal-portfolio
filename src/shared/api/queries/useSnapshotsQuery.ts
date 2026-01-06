/**
 * Snapshots Query Hook (Portfolio History)
 * 
 * 포트폴리오 스냅샷 히스토리를 가져오는 훅
 */

import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { ApiClient, BackendSnapshot } from '@lib/api';
import { queryKeys } from '../queryKeys';

interface HistoryPoint {
    date: string;
    value: number;
}

/**
 * 포트폴리오 스냅샷 조회 (원본)
 */
export function useSnapshotsRawQuery(
    apiClient: ApiClient | null,
    days = 180,
    options?: Omit<UseQueryOptions<BackendSnapshot[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.snapshots(days),
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchSnapshots(days);
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 10, // 10분
        ...options,
    });
}

/**
 * 차트용 히스토리 데이터 조회
 */
export function useHistoryDataQuery(
    apiClient: ApiClient | null,
    days = 365,
    options?: Omit<UseQueryOptions<HistoryPoint[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.snapshots(days),
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            const data = await apiClient.fetchSnapshots(days);
            return data.map((snap) => {
                const d = new Date(snap.snapshot_at);
                const label = d.toLocaleDateString('ko-KR', {
                    month: '2-digit',
                    day: '2-digit',
                });
                return {
                    date: label,
                    value: snap.total_value,
                };
            });
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 10,
        ...options,
    });
}
