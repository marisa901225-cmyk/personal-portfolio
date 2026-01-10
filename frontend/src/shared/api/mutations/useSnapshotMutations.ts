/**
 * Snapshot Mutations
 * 
 * 포트폴리오 스냅샷 생성을 위한 Mutation 훅
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiClient } from '@/shared/api/client';
import { queryKeys } from '../queryKeys';

/**
 * 스냅샷 생성 Mutation
 */
export function useCreateSnapshot(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.createSnapshot();
        },
        onSuccess: () => {
            // 스냅샷 목록 무효화
            queryClient.invalidateQueries({ queryKey: ['snapshots'] });
        },
    });
}
