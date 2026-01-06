import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiClient } from '../lib/api';
import { TradeType } from '../lib/types';
import { queryKeys } from '../src/shared/api/queryKeys';

export const useTradeMutation = (apiClient: ApiClient) => {
    const queryClient = useQueryClient();

    const tradeAssetMutation = useMutation({
        mutationFn: async ({ backendId, type, quantity, price }: {
            backendId: number;
            type: TradeType;
            quantity: number;
            price: number
        }) => {
            return await apiClient.createTrade(backendId, type, quantity, price);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
            queryClient.invalidateQueries({ queryKey: queryKeys.trades });
        },
    });

    return {
        tradeAsset: tradeAssetMutation.mutateAsync,
    };
};
