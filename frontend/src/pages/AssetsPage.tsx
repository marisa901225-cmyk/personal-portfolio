/**
 * Assets Page (자산 목록)
 * 
 * React Query를 사용해 자산 목록을 로드하고 관리합니다.
 */

import React from 'react';
import { AssetList } from '@components/AssetList';
import { useApiClient, isApiEnabled } from '@/shared/api/apiClient';
import { useAssetsQuery } from '@/shared/api/queries';
import { useDeleteAsset, useUpdateAsset, useCreateTrade } from '@/shared/api/mutations';
import { useSettings } from '@hooks/useSettings';
import { AssetCategory } from '@lib/types';
import { Loader2 } from 'lucide-react';

export const AssetsPage: React.FC = () => {
    const { settings } = useSettings();
    const apiClient = useApiClient({
        serverUrl: settings.serverUrl,
        apiToken: settings.apiToken,
    });

    const enabled = isApiEnabled({ serverUrl: settings.serverUrl, apiToken: settings.apiToken });

    const assetsQuery = useAssetsQuery(apiClient, { enabled });
    const deleteAssetMutation = useDeleteAsset(apiClient);
    const updateAssetMutation = useUpdateAsset(apiClient);
    const createTradeMutation = useCreateTrade(apiClient);

    if (!enabled) {
        return (
            <div className="flex flex-col items-center justify-center py-20 text-center">
                <p className="text-slate-500">서버 연결이 필요합니다.</p>
            </div>
        );
    }

    if (assetsQuery.isLoading) {
        return (
            <div className="flex flex-col items-center justify-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                <p className="text-slate-500 mt-4">자산 목록 로딩 중...</p>
            </div>
        );
    }

    const assets = assetsQuery.data ?? [];

    const handleDelete = (id: string) => {
        const asset = assets.find(a => a.id === id);
        if (!asset?.backendId) return;
        if (!window.confirm('정말 이 자산을 삭제하시겠습니까?')) return;
        deleteAssetMutation.mutate(asset.backendId);
    };

    const handleTrade = (id: string, type: 'BUY' | 'SELL', quantity: number, price: number) => {
        const asset = assets.find(a => a.id === id);
        if (!asset?.backendId) return;
        createTradeMutation.mutate({
            assetId: asset.backendId,
            type,
            quantity,
            price,
        });
    };

    const handleUpdateAsset = (
        id: string,
        updates: {
            name?: string;
            ticker?: string;
            indexGroup?: string;
            category?: AssetCategory;
            amount?: number;
            purchasePrice?: number;
        }
    ) => {
        const asset = assets.find(a => a.id === id);
        if (!asset?.backendId) return;
        updateAssetMutation.mutate({
            assetId: asset.backendId,
            payload: {
                name: updates.name,
                ticker: updates.ticker,
                index_group: updates.indexGroup,
                category: updates.category,
                amount: updates.amount,
                purchase_price: updates.purchasePrice,
            },
        });
    };

    const handleUpdateCash = async (id: string, newBalance: number) => {
        const asset = assets.find(a => a.id === id);
        if (!asset?.backendId) return;
        updateAssetMutation.mutate({
            assetId: asset.backendId,
            payload: {
                current_price: newBalance,
                purchase_price: newBalance,
            },
        });
    };

    return (
        <AssetList
            assets={assets}
            onDelete={handleDelete}
            onTrade={handleTrade}
            onUpdateAsset={handleUpdateAsset}
            onUpdateCash={handleUpdateCash}
            onRestoreFromBackup={async () => { }}
            usdFxNow={settings.usdFxNow}
            indexGroupOptions={settings.targetIndexAllocations?.map(a => a.indexGroup) || []}
        />
    );
};

export default AssetsPage;
