/**
 * Asset Mutations
 * 
 * 자산 생성/수정/삭제를 위한 Mutation 훅들
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiClient } from '@/shared/api/client';
import { AssetCategory } from '@lib/types';
import { queryKeys } from '../queryKeys';

interface CreateAssetPayload {
    name: string;
    ticker?: string;
    category: AssetCategory;
    currency: 'KRW' | 'USD';
    amount: number;
    current_price: number;
    purchase_price?: number;
    realized_profit?: number;
    index_group?: string;
    cma_config?: {
        principal: number;
        annual_rate: number;
        tax_rate: number;
        start_date: string;
    } | null;
}

interface UpdateAssetPayload {
    name?: string;
    ticker?: string | null;
    category?: AssetCategory;
    amount?: number;
    current_price?: number;
    purchase_price?: number;
    realized_profit?: number;
    index_group?: string | null;
    cma_config?: {
        principal: number;
        annual_rate: number;
        tax_rate: number;
        start_date: string;
    } | null;
}

/**
 * 자산 생성 Mutation
 */
export function useCreateAsset(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (payload: CreateAssetPayload) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.createAsset(payload);
        },
        onSuccess: () => {
            // 포트폴리오 데이터 무효화 → 자동 refetch
            queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
        },
    });
}

/**
 * 자산 수정 Mutation
 */
export function useUpdateAsset(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ assetId, payload }: { assetId: number; payload: UpdateAssetPayload }) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.updateAsset(assetId, payload);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
        },
    });
}

/**
 * 자산 삭제 Mutation
 */
export function useDeleteAsset(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (assetId: number) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.deleteAsset(assetId);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
        },
    });
}
