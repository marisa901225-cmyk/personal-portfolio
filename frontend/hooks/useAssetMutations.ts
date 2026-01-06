import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiClient } from '../lib/api';
import { Asset, AssetCategory } from '../lib/types';
import { CmaConfig } from '../lib/utils/cmaConfig';
import { alertError } from '../lib/utils/errors';
import { queryKeys } from '../src/shared/api/queryKeys';

export const useAssetMutations = (apiClient: ApiClient, isRemoteEnabled: boolean) => {
    const queryClient = useQueryClient();

    const invalidate = () => {
        queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
        queryClient.invalidateQueries({ queryKey: ['snapshots'] }); // Use broad key to match queryKeys.snapshots(days)
        queryClient.invalidateQueries({ queryKey: queryKeys.cashflows });
    };

    const addAssetMutation = useMutation({
        mutationFn: async (newAsset: Asset) => {
            if (!isRemoteEnabled) return;
            const payload = {
                name: newAsset.name,
                ticker: newAsset.ticker,
                category: newAsset.category,
                currency: newAsset.currency,
                amount: newAsset.amount,
                current_price: newAsset.currentPrice,
                purchase_price: newAsset.purchasePrice,
                realized_profit: newAsset.realizedProfit ?? 0,
                index_group: newAsset.indexGroup,
                cma_config: newAsset.cmaConfig ? {
                    principal: newAsset.cmaConfig.principal,
                    annual_rate: newAsset.cmaConfig.annualRate,
                    tax_rate: newAsset.cmaConfig.taxRate,
                    start_date: newAsset.cmaConfig.startDate,
                } : null,
            };
            await apiClient.createAsset(payload);
        },
        onSuccess: invalidate,
    });

    const deleteAssetMutation = useMutation({
        mutationFn: async (backendId: number) => {
            await apiClient.deleteAsset(backendId);
        },
        onSuccess: invalidate,
    });

    const updateAssetMutation = useMutation({
        mutationFn: async ({ backendId, updates }: { backendId: number; updates: any }) => {
            const payload: any = {};
            if (updates.name !== undefined) payload.name = updates.name;
            if (updates.ticker !== undefined) payload.ticker = updates.ticker || null;
            if (updates.indexGroup !== undefined) payload.index_group = updates.indexGroup || null;
            if (updates.category !== undefined) payload.category = updates.category;
            if (updates.amount !== undefined) payload.amount = updates.amount;
            if (updates.purchasePrice !== undefined) payload.purchase_price = updates.purchasePrice;

            return await apiClient.updateAsset(backendId, payload);
        },
        onSuccess: invalidate,
    });

    const updateCashBalanceMutation = useMutation({
        mutationFn: async ({ backendId, currentPrice, amount, purchasePrice, cmaConfig }: {
            backendId: number;
            currentPrice: number;
            amount?: number;
            purchasePrice?: number;
            cmaConfig?: CmaConfig | null
        }) => {
            const payload: any = { current_price: currentPrice };
            if (amount !== undefined) payload.amount = amount;
            if (purchasePrice !== undefined) payload.purchase_price = purchasePrice;
            payload.cma_config = cmaConfig ? {
                principal: cmaConfig.principal,
                annual_rate: cmaConfig.annualRate,
                tax_rate: cmaConfig.taxRate,
                start_date: cmaConfig.startDate,
            } : null;

            await apiClient.updateAsset(backendId, payload);
        },
        onSuccess: invalidate,
    });

    return {
        addAsset: addAssetMutation.mutateAsync,
        deleteAsset: deleteAssetMutation.mutateAsync,
        updateAsset: updateAssetMutation.mutateAsync,
        updateCashBalance: updateCashBalanceMutation.mutateAsync,
    };
};
