/**
 * Assets Page (자산 목록)
 * 
 * React Query를 사용해 자산 목록을 로드하고 관리합니다.
 */

import React from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { AssetList } from '@components/AssetList';
import { NewsOverlay } from '@components/NewsOverlay';
import { queryKeys } from '@/shared/api';
import { useApiClient, isApiEnabled } from '@/shared/api/apiClient';
import { useAssetsQuery } from '@/shared/api/queries';
import { useDeleteAsset, useUpdateAsset, useCreateTrade } from '@/shared/api/mutations';
import { restorePortfolioFromBackup } from '@/features/portfolio';
import type { ImportedAssetSnapshot } from '@/shared/portfolio';
import { useSettings } from '@hooks/useSettings';
import type { CmaConfig } from '@/shared/portfolio';
import { AssetCategory } from '@lib/types';
import { Loader2 } from 'lucide-react';
import { alertError, isApiErrorStatus } from '@/shared/errors';

export const AssetsPage: React.FC = () => {
    const { settings } = useSettings();
    const queryClient = useQueryClient();
    const apiClient = useApiClient({
        serverUrl: settings.serverUrl,
        apiToken: settings.apiToken,
        cookieAuth: settings.cookieAuth,
    });

    const enabled = isApiEnabled({
        serverUrl: settings.serverUrl,
        apiToken: settings.apiToken,
        cookieAuth: settings.cookieAuth,
    });

    const assetsQuery = useAssetsQuery(apiClient, { enabled });
    const deleteAssetMutation = useDeleteAsset(apiClient);
    const updateAssetMutation = useUpdateAsset(apiClient);
    const createTradeMutation = useCreateTrade(apiClient);

    // Hook을 조건부 리턴 이전에 호출 (React Rules of Hooks)
    const [selectedNewsQuery, setSelectedNewsQuery] = React.useState<string | null>(null);
    const [selectedNewsTicker, setSelectedNewsTicker] = React.useState<string | null>(null);

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

    const refreshPortfolioForStaleId = async (error: unknown): Promise<void> => {
        if (!isApiErrorStatus(error, 404)) return;
        await queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
        await queryClient.refetchQueries({ queryKey: queryKeys.portfolio });
    };

    const handleDelete = (id: string) => {
        const asset = assets.find(a => a.id === id);
        if (!asset?.backendId) return;
        if (!window.confirm('정말 이 자산을 삭제하시겠습니까?')) return;
        deleteAssetMutation.mutate(asset.backendId, {
            onError: (error) => {
                void refreshPortfolioForStaleId(error);
                alertError('Delete asset error', error, {
                    default: '자산 삭제에 실패했습니다.',
                    unauthorized: '자산 삭제 권한이 없습니다. 다시 로그인 후 시도해주세요.',
                    network: '서버 연결 문제로 자산 삭제에 실패했습니다.',
                    clientError: '자산 삭제 요청이 거부되었습니다.',
                    serverError: '서버 오류로 자산 삭제에 실패했습니다.',
                });
            },
        });
    };

    const handleTrade = (id: string, type: 'BUY' | 'SELL', quantity: number, price: number) => {
        const asset = assets.find(a => a.id === id);
        if (!asset?.backendId) return;
        createTradeMutation.mutate(
            {
                assetId: asset.backendId,
                type,
                quantity,
                price,
            },
            {
                onError: (error) => {
                    void refreshPortfolioForStaleId(error);
                    alertError('Create trade error', error, {
                        default: '거래 처리에 실패했습니다.',
                        unauthorized: '거래 처리 권한이 없습니다. 다시 로그인 후 시도해주세요.',
                        network: '서버 연결 문제로 거래 처리에 실패했습니다.',
                        clientError: '거래 요청이 거부되었습니다.',
                        serverError: '서버 오류로 거래 처리에 실패했습니다.',
                    });
                },
            },
        );
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
            currentPrice?: number;
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
                current_price: updates.currentPrice,
            },
        });
    };

    const handleUpdateCash = (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => {
        const asset = assets.find(a => a.id === id);
        if (!asset?.backendId) return;
        const isCash = asset.category === AssetCategory.CASH;
        const nextAmount = isCash ? 1 : asset.amount > 0 ? asset.amount : 1;
        const nextCurrentPrice = isCash ? newBalance : newBalance / nextAmount;

        const payload: {
            current_price: number;
            amount?: number;
            purchase_price?: number;
            cma_config?: {
                principal: number;
                annual_rate: number;
                tax_rate: number;
                start_date: string;
            } | null;
        } = { current_price: nextCurrentPrice };

        if (isCash) {
            payload.amount = 1;
            payload.purchase_price = newBalance;
            payload.cma_config = cmaConfig ? {
                principal: cmaConfig.principal,
                annual_rate: cmaConfig.annualRate,
                tax_rate: cmaConfig.taxRate,
                start_date: cmaConfig.startDate,
            } : null;
        }

        updateAssetMutation.mutate({
            assetId: asset.backendId,
            payload,
        });
    };

    const handleRestoreFromBackup = async (snapshot: ImportedAssetSnapshot[]) => {
        if (!apiClient) return;
        await restorePortfolioFromBackup({
            snapshot,
            isRemoteEnabled: enabled,
            apiClient,
            setAssets: () => { },
            setTradeHistory: () => { },
            loadPortfolioFromServer: async () => {
                await queryClient.refetchQueries({ queryKey: queryKeys.portfolio });
                await queryClient.refetchQueries({ queryKey: queryKeys.trades });
                await queryClient.refetchQueries({ queryKey: queryKeys.snapshots(365) });
                await queryClient.refetchQueries({ queryKey: queryKeys.cashflows });
            },
        });
    };

    return (
        <>
            <AssetList
                assets={assets}
                onDelete={handleDelete}
                onTrade={handleTrade}
                onUpdateAsset={handleUpdateAsset}
                onUpdateCash={handleUpdateCash}
                onRestoreFromBackup={handleRestoreFromBackup}
                onSelectNewsQuery={(query, ticker) => {
                    setSelectedNewsQuery(query);
                    setSelectedNewsTicker(ticker || null);
                }}
                usdFxNow={settings.usdFxNow}
                indexGroupOptions={settings.targetIndexAllocations?.map(a => a.indexGroup) || []}
            />

            {apiClient && (
                <NewsOverlay
                    isOpen={!!selectedNewsQuery}
                    onClose={() => {
                        setSelectedNewsQuery(null);
                        setSelectedNewsTicker(null);
                    }}
                    query={selectedNewsQuery || ''}
                    ticker={selectedNewsTicker}
                    apiClient={apiClient}
                />
            )}
        </>
    );
};

export default AssetsPage;
