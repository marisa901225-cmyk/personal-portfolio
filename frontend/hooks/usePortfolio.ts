
import { useMemo, useCallback, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Asset, AppSettings, AssetCategory, TradeType, TradeRecord } from '../lib/types';
import { ApiClient, mapBackendAssetToFrontend, mapBackendTradesToFrontend, type BackendPortfolioResponse } from '@/shared/api/client';
import { CmaConfig } from '@/shared/portfolio';
import type { ImportedAssetSnapshot } from '@/shared/portfolio';
import { syncPortfolioPrices, restorePortfolioFromBackup } from '@/features/portfolio';
import { queryKeys } from '@/shared/api/queryKeys';

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
  const apiClient = useMemo(
    () => new ApiClient(settings.serverUrl, settings.apiToken),
    [settings.serverUrl, settings.apiToken]
  );

  // === Queries (통합된 API 레이어 사용) ===
  const assetsQuery = useQuery<BackendPortfolioResponse, Error, {
    assets: Asset[];
    tradeHistory: TradeRecord[];
    summary: BackendPortfolioResponse['summary'];
  }>({
    queryKey: queryKeys.portfolio,
    queryFn: async () => apiClient.fetchPortfolio(),
    enabled: isRemoteEnabled,
    select: (data) => {
      const mappedAssets = data.assets.map(mapBackendAssetToFrontend);
      const mappedTrades = mapBackendTradesToFrontend(data.trades, mappedAssets);
      return { assets: mappedAssets, tradeHistory: mappedTrades, summary: data.summary };
    },
  });

  const snapshotsQuery = useQuery({
    queryKey: queryKeys.snapshots(365),
    queryFn: async () => {
      const data = await apiClient.fetchSnapshots(365);
      return data.map((snap) => ({
        date: new Date(snap.snapshot_at).toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' }),
        value: snap.total_value,
      }));
    },
    enabled: isRemoteEnabled,
  });

  const cashflowsQuery = useQuery({
    queryKey: queryKeys.cashflows,
    queryFn: async () => {
      const data = await apiClient.fetchCashflows();
      return data.map((cf) => ({
        year: cf.year.toString(),
        deposit: cf.deposit,
        withdrawal: cf.withdrawal,
        net: cf.net,
        note: cf.note ?? undefined,
      }));
    },
    enabled: isRemoteEnabled,
  });

  // === Mutations ===
  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
    queryClient.invalidateQueries({ queryKey: ['snapshots'] });
    queryClient.invalidateQueries({ queryKey: queryKeys.cashflows });
  }, [queryClient]);

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
    onSuccess: invalidateAll,
  });

  const deleteAssetMutation = useMutation({
    mutationFn: async (backendId: number) => {
      await apiClient.deleteAsset(backendId);
    },
    onSuccess: invalidateAll,
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
      if (updates.currentPrice !== undefined) payload.current_price = updates.currentPrice;
      return await apiClient.updateAsset(backendId, payload);
    },
    onSuccess: invalidateAll,
  });

  const tradeMutation = useMutation({
    mutationFn: async ({ backendId, type, quantity, price }: { backendId: number; type: TradeType; quantity: number; price: number }) => {
      return await apiClient.createTrade(backendId, type, quantity, price);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio });
      queryClient.invalidateQueries({ queryKey: queryKeys.trades });
    },
  });

  // === Derived Data ===
  const assets = assetsQuery.data?.assets ?? [];
  const tradeHistory = assetsQuery.data?.tradeHistory ?? [];
  const historyData = snapshotsQuery.data ?? [];
  const yearlyCashflows = cashflowsQuery.data ?? [];
  const summaryFromServer = assetsQuery.data?.summary;

  // === Handlers ===
  const reload = useCallback(async () => {
    await queryClient.refetchQueries({ queryKey: queryKeys.portfolio });
    await queryClient.refetchQueries({ queryKey: queryKeys.snapshots(365) });
    await queryClient.refetchQueries({ queryKey: queryKeys.cashflows });
  }, [queryClient]);

  const handleUpdateAsset = useCallback(async (id: string, updates: any) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;
    await updateAssetMutation.mutateAsync({ backendId: target.backendId, updates });
  }, [assets, updateAssetMutation, isRemoteEnabled]);

  const handleUpdateCashBalance = useCallback(async (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;

    const isCash = target.category === AssetCategory.CASH;
    const nextAmount = isCash ? 1 : target.amount > 0 ? target.amount : 1;
    const nextCurrentPrice = isCash ? newBalance : newBalance / nextAmount;

    const payload: any = { current_price: nextCurrentPrice };
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
    await apiClient.updateAsset(target.backendId, payload);
    invalidateAll();
  }, [assets, apiClient, invalidateAll, isRemoteEnabled]);

  const handleTradeAsset = useCallback(async (id: string, type: TradeType, quantity: number, price: number) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;
    await tradeMutation.mutateAsync({ backendId: target.backendId, type, quantity, price });
  }, [assets, tradeMutation, isRemoteEnabled]);

  const handleDeleteAsset = useCallback(async (id: string) => {
    const target = assets.find(a => a.id === id);
    if (!target?.backendId || !isRemoteEnabled) return;
    await deleteAssetMutation.mutateAsync(target.backendId);
  }, [assets, deleteAssetMutation, isRemoteEnabled]);

  const handleSyncPrices = useCallback(async (options?: { createSnapshot?: boolean; onSuccess?: () => void }) => {
    setSyncing(true);
    try {
      await syncPortfolioPrices({
        settings, assets, apiClient, isRemoteEnabled,
        setAssets: () => { },
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
    addAsset: addAssetMutation.mutateAsync,
    deleteAsset: handleDeleteAsset,
    tradeAsset: handleTradeAsset,
    syncPrices: handleSyncPrices,
    updateAsset: handleUpdateAsset,
    updateCashBalance: handleUpdateCashBalance,
    restoreFromBackup: async (snapshot) => {
      await restorePortfolioFromBackup({
        snapshot, isRemoteEnabled, apiClient,
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
