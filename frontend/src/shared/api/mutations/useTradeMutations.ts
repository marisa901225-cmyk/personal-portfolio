/**
 * Trade Mutations
 * 
 * 거래(매수/매도) 생성을 위한 Mutation 훅
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiClient } from '@/shared/api/client';
import { TradeType } from '@lib/types';
import { queryKeys } from '../queryKeys';

interface CreateTradeParams {
    assetId: number;
    type: TradeType;
    quantity: number;
    price: number;
}

/**
 * 거래 생성 Mutation
 */
export function useCreateTrade(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ assetId, type, quantity, price }: CreateTradeParams) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.createTrade(assetId, type, quantity, price);
        },
        onSuccess: () => {
            // 포트폴리오와 거래 내역 모두 무효화
            queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
            queryClient.invalidateQueries({ queryKey: queryKeys.trades });
        },
    });
}
