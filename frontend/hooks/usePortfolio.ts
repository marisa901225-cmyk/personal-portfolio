
import { useMemo, useCallback, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Asset, AppSettings, AssetCategory, TradeType, TradeRecord } from '../lib/types';
import { ApiClient } from '../lib/api';
import { CmaConfig } from '../lib/utils/cmaConfig';
import type { ImportedAssetSnapshot } from './portfolioTypes';
import { syncPortfolioPrices } from './portfolioSync';
import { restorePortfolioFromBackup } from './portfolioBackup';
import { usePortfolioQueries } from './usePortfolioQueries';
import { useAssetMutations } from './useAssetMutations';
import { useTradeMutation } from './useTradeMutation';
import { queryKeys } from '../src/shared/api/queryKeys';

export interface HistoryPoint {
  date: string;
  value: number;
  stockValue?: number;
  realEstateValue?: number;
}

export interface YearlyCashflowData {
  year: string;
  deposit: number;
  withdrawal: number;
  net: number;
  note?: string;
}

export interface UsePortfolioResult {
  assets: Asset[];
  tradeHistory: TradeRecord[];
  historyData: HistoryPoint[];
  summaryFromServer?: any;
  isSyncing: boolean;
  isManualSyncing: boolean;
  addAsset: (newAsset: Asset) => Promise<void>;
  deleteAsset: (id: string) => Promise<void>;
  tradeAsset: (id: string, type: TradeType, quantity: number, price: number) => Promise<void>;
  syncPrices: (options?: { createSnapshot?: boolean; onSuccess?: () => void }) => Promise<void>;
  updateAsset: (id: string, updates: any) => Promise<void>;
  updateCashBalance: (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => Promise<void>;
  restoreFromBackup: (snapshot: ImportedAssetSnapshot[]) => Promise<void>;
  yearlyCashflows: YearlyCashflowData[];
  apiClient: ApiClient;
  reload: () => Promise<void>;
}

export const usePortfolio = (settings: AppSettings): UsePortfolioResult => {
  const queryClient = useQueryClient();
  const [syncing, setSyncing] = useState(false);
  const isRemoteEnabled = Boolean(settings.serverUrl && settings.apiToken);
  const apiClient = useMemo(() => new ApiClient(settings.serverUrl, settings.apiToken), [settings.serverUrl, settings.apiToken]);

  const { assetsQuery, snapshotsQuery, cashflowsQuery } = usePortfolioQueries(settings, apiClient);
  const assetMutations = useAssetMutations(apiClient, isRemoteEnabled);
  const tradeMutation = useTradeMutation(apiClient);

  const assets = assetsQuery.data?.assets ?? [];
  const tradeHistory = assetsQuery.data?.tradeHistory ?? [];
  const historyData = snapshotsQuery.data ?? [];
  const yearlyCashflows = cashflowsQuery.data ?? [];
  const summaryFromServer = assetsQuery.data?.summary;

  const reload = useCallback(async () => {
    await queryClient.refetchQueries({ queryKey: queryKeys.legacyPortfolio });
    await queryClient.refetchQueries({ queryKey: queryKeys.portfolio });
    await queryClient.refetchQueries({ queryKey: queryKeys.snapshots(365) });
    await queryClient.refetchQueries({ queryKey: queryKeys.cashflows });
  }, [queryClient]);

  const handleUpdateAsset = useCallback(async (id: string, updates: any) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;
    await assetMutations.updateAsset({ backendId: target.backendId, updates });
  }, [assets, assetMutations, isRemoteEnabled]);

  const handleUpdateCashBalance = useCallback(async (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;

    const isCash = target.category === AssetCategory.CASH;
    const nextAmount = isCash ? 1 : target.amount > 0 ? target.amount : 1;
    const nextCurrentPrice = isCash ? newBalance : newBalance / nextAmount;

    await assetMutations.updateCashBalance({
      backendId: target.backendId,
      currentPrice: nextCurrentPrice,
      amount: isCash ? 1 : undefined,
      purchasePrice: isCash ? newBalance : undefined,
      cmaConfig: isCash ? cmaConfig : undefined
    });
  }, [assets, assetMutations, isRemoteEnabled]);

  const handleTradeAsset = useCallback(async (id: string, type: TradeType, quantity: number, price: number) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;
    await tradeMutation.tradeAsset({ backendId: target.backendId, type, quantity, price });
  }, [assets, tradeMutation, isRemoteEnabled]);

  const handleDeleteAsset = useCallback(async (id: string) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;
    await assetMutations.deleteAsset(target.backendId);
  }, [assets, assetMutations, isRemoteEnabled]);

  const handleSyncPrices = useCallback(async (options?: { createSnapshot?: boolean; onSuccess?: () => void }) => {
    setSyncing(true);
    try {
      await syncPortfolioPrices({
        settings,
        assets,
        apiClient,
        isRemoteEnabled,
        setAssets: () => { }, // Handled by invalidate
        setIsSyncing: () => { },
        loadPortfolioFromServer: reload,
        onSuccess: options?.onSuccess,
      });

      if (options?.createSnapshot && isRemoteEnabled) {
        await apiClient.createSnapshot();
        await queryClient.refetchQueries({ queryKey: queryKeys.snapshots(365) });
      }
    } finally {
      setSyncing(false);
    }
  }, [settings, assets, apiClient, isRemoteEnabled, reload, queryClient]);

  return {
    assets,
    tradeHistory,
    historyData,
    summaryFromServer,
    isSyncing: syncing || assetsQuery.isLoading || snapshotsQuery.isLoading,
    isManualSyncing: syncing,
    addAsset: assetMutations.addAsset,
    deleteAsset: handleDeleteAsset,
    tradeAsset: handleTradeAsset,
    syncPrices: handleSyncPrices,
    updateAsset: handleUpdateAsset,
    updateCashBalance: handleUpdateCashBalance,
    restoreFromBackup: async (snapshot) => {
      await restorePortfolioFromBackup({
        snapshot,
        isRemoteEnabled,
        apiClient,
        setAssets: () => { },
        setTradeHistory: () => { },
        loadPortfolioFromServer: reload,
      });
    },
    yearlyCashflows,
    apiClient,
    reload,
  };
};
