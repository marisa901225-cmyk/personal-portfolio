import { useEffect, useState, useMemo } from 'react';
import { Asset, AppSettings, AssetCategory, TradeRecord, TradeType } from '../types';
import {
  ApiClient,
  BackendPortfolioResponse,
  BackendTrade,
  mapBackendAssetToFrontend,
  mapBackendTradesToFrontend,
  BackendPortfolioSummary,
} from '../backendClient';
import { CmaConfig } from '../cmaConfig';
import type { ImportedAssetSnapshot } from './portfolioTypes';
import { syncPortfolioPrices } from './portfolioSync';
import { restorePortfolioFromBackup } from './portfolioBackup';
import { alertError } from '../errors';

interface HistoryPoint {
  date: string;
  value: number;
}

interface UsePortfolioResult {
  assets: Asset[];
  tradeHistory: TradeRecord[];
  historyData: HistoryPoint[];
  summaryFromServer?: BackendPortfolioSummary;
  isSyncing: boolean;
  addAsset: (newAsset: Asset) => Promise<void>;
  deleteAsset: (id: string) => Promise<void>;
  tradeAsset: (id: string, type: TradeType, quantity: number, price: number) => Promise<void>;
  syncPrices: () => Promise<void>;
  updateAsset: (
    id: string,
    updates: {
      name?: string;
      ticker?: string;
      indexGroup?: string;
      category?: AssetCategory;
      amount?: number;
      purchasePrice?: number;
    },
  ) => Promise<void>;
  updateCashBalance: (id: string, newBalance: number, cmaConfig?: CmaConfig | null) => Promise<void>;
  restoreFromBackup: (snapshot: ImportedAssetSnapshot[]) => Promise<void>;
}

export const usePortfolio = (settings: AppSettings): UsePortfolioResult => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeRecord[]>([]);
  const [historyData, setHistoryData] = useState<HistoryPoint[]>([]);
  const [summaryFromServer, setSummaryFromServer] = useState<BackendPortfolioSummary | undefined>(undefined);
  const [isSyncing, setIsSyncing] = useState(false);

  const isRemoteEnabled = Boolean(settings.serverUrl && settings.apiToken);

  const apiClient = useMemo(
    () => new ApiClient(settings.serverUrl, settings.apiToken),
    [settings.serverUrl, settings.apiToken]
  );

  const loadPortfolioFromServer = async (): Promise<void> => {
    try {
      const data = await apiClient.fetchPortfolio();
      const mappedAssets = data.assets.map(mapBackendAssetToFrontend);
      const mappedTrades = mapBackendTradesToFrontend(data.trades, mappedAssets);
      setAssets(mappedAssets);
      setTradeHistory(mappedTrades);
      setSummaryFromServer(data.summary);
    } catch (error) {
      alertError('Failed to load portfolio from server', error, {
        default: '포트폴리오를 불러오지 못했습니다.\n서버 상태를 확인해주세요.',
        unauthorized: '포트폴리오를 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
        network: '포트폴리오를 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
      });
    }
  };

  const loadHistoryFromServer = async (): Promise<void> => {
    if (!isRemoteEnabled) {
      setHistoryData([]);
      return;
    }

    try {
      const data = await apiClient.fetchSnapshots(180);
      const mapped = data.map((snap) => {
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
      setHistoryData(mapped);
    } catch (error) {
      console.warn('Failed to load portfolio snapshots', error);
    }
  };

  useEffect(() => {
    if (!isRemoteEnabled) {
      setHistoryData([]);
      setSummaryFromServer(undefined);
      return;
    }

    void loadPortfolioFromServer();
    void loadHistoryFromServer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isRemoteEnabled, apiClient]); // apiClient changes when settings change

  const addAsset = async (newAsset: Asset): Promise<void> => {
    if (!isRemoteEnabled) {
      setAssets((prev) => [...prev, newAsset]);
      return;
    }

    try {
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
        cma_config: newAsset.cmaConfig
          ? {
            principal: newAsset.cmaConfig.principal,
            annual_rate: newAsset.cmaConfig.annualRate,
            tax_rate: newAsset.cmaConfig.taxRate,
            start_date: newAsset.cmaConfig.startDate,
          }
          : null,
      };

      await apiClient.createAsset(payload);
      await loadPortfolioFromServer();
    } catch (error) {
      alertError('Create asset error', error, {
        default:
          '자산을 서버에 저장하지 못했습니다 (또는 서버 연결 실패).\n현재 세션에서만 브라우저에 임시로 반영됩니다.',
        unauthorized: '자산을 저장하지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
        network:
          '자산을 서버에 저장하지 못했습니다.\n서버 연결을 확인해주세요.\n현재 세션에서만 브라우저에 임시로 반영됩니다.',
      });
      setAssets((prev) => [...prev, newAsset]);
    }
  };

  const deleteAsset = async (id: string): Promise<void> => {
    const target = assets.find((a) => a.id === id);

    if (target?.backendId && isRemoteEnabled) {
      try {
        await apiClient.deleteAsset(target.backendId);
        await loadPortfolioFromServer();
      } catch (error) {
        alertError('Delete asset error', error, {
          default: '자산을 서버에서 삭제하지 못했습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
          unauthorized: '자산을 삭제하지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '자산을 서버에서 삭제하지 못했습니다.\n서버 연결을 확인해주세요.',
        });
      }
    }

    setAssets((prev) => prev.filter((a) => a.id !== id));
  };

  const tradeAsset = async (
    id: string,
    type: TradeType,
    quantity: number,
    price: number,
  ): Promise<void> => {
    if (quantity <= 0 || price <= 0) {
      alert('수량과 가격은 0보다 커야 합니다.');
      return;
    }

    const targetAsset = assets.find((a) => a.id === id);
    if (!targetAsset) return;

    if (type === 'SELL' && quantity > targetAsset.amount) {
      alert('보유 수량보다 많이 매도할 수 없습니다.');
      return;
    }

    if (targetAsset.backendId && isRemoteEnabled) {
      try {
        const backendTrade = await apiClient.createTrade(
          targetAsset.backendId,
          type,
          quantity,
          price
        );

        await loadPortfolioFromServer();

        setTradeHistory((prev) => {
          const record: TradeRecord = {
            id: backendTrade.id.toString(),
            assetId: backendTrade.asset_id.toString(),
            assetName: targetAsset.name,
            ticker: targetAsset.ticker,
            type: backendTrade.type,
            quantity: backendTrade.quantity,
            price: backendTrade.price,
            timestamp: backendTrade.timestamp,
            realizedDelta: backendTrade.realized_delta ?? undefined,
          };
          return [record, ...prev].slice(0, 20);
        });
        return;
      } catch (error) {
        alertError('Trade request error', error, {
          default: '서버와 통신 중 오류가 발생했습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
          unauthorized: '거래를 저장하지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '서버와 통신할 수 없습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
        });
      }
    }

    let realizedDelta: number | undefined;
    if (type === 'SELL') {
      const avgCost = targetAsset.purchasePrice ?? targetAsset.currentPrice;
      realizedDelta = (price - avgCost) * quantity;
    }

    setAssets((prevAssets) =>
      prevAssets.reduce((acc: Asset[], asset) => {
        if (asset.id !== id) {
          acc.push(asset);
          return acc;
        }

        const qty = quantity;
        const tradePrice = price;

        if (type === 'BUY') {
          const prevAmount = asset.amount;
          const prevPurchasePrice = asset.purchasePrice ?? asset.currentPrice;
          const newAmount = prevAmount + qty;
          const newPurchasePrice =
            newAmount > 0
              ? (prevAmount * prevPurchasePrice + qty * tradePrice) / newAmount
              : prevPurchasePrice;

          acc.push({
            ...asset,
            amount: newAmount,
            purchasePrice: newPurchasePrice,
          });
        } else {
          const prevAmount = asset.amount;
          const prevPurchasePrice = asset.purchasePrice ?? asset.currentPrice;
          const newAmount = prevAmount - qty;
          const avgCost = prevPurchasePrice;
          const prevRealized = asset.realizedProfit || 0;
          const delta = (tradePrice - avgCost) * qty;
          const updatedRealized = prevRealized + delta;

          if (newAmount <= 0) {
            return acc;
          }

          acc.push({
            ...asset,
            amount: newAmount,
            purchasePrice: prevPurchasePrice,
            realizedProfit: updatedRealized,
          });
        }

        return acc;
      }, []),
    );

    const record: TradeRecord = {
      id: Date.now().toString(),
      assetId: targetAsset.id,
      assetName: targetAsset.name,
      ticker: targetAsset.ticker,
      type,
      quantity,
      price,
      timestamp: new Date().toISOString(),
      realizedDelta,
    };
    setTradeHistory((prev) => [record, ...prev].slice(0, 20));
  };

  const syncPrices = async (): Promise<void> => {
    await syncPortfolioPrices({
      settings,
      assets,
      apiClient,
      isRemoteEnabled,
      setAssets,
      setIsSyncing,
      loadPortfolioFromServer,
    });
  };

  const restoreFromBackup = async (snapshot: ImportedAssetSnapshot[]): Promise<void> => {
    await restorePortfolioFromBackup({
      snapshot,
      isRemoteEnabled,
      apiClient,
      setAssets,
      setTradeHistory,
      loadPortfolioFromServer,
    });
  };

  const updateCashBalance = async (id: string, newBalance: number, cmaConfig?: CmaConfig | null): Promise<void> => {
    if (newBalance < 0) {
      alert('예비금은 0원보다 작을 수 없습니다.');
      return;
    }

    const target = assets.find((a) => a.id === id);
    if (!target) return;
    const isCash = target.category === AssetCategory.CASH;
    const isRealEstate = target.category === AssetCategory.REAL_ESTATE;
    if (!isCash && !isRealEstate) {
      alert('금액 직접 수정은 "현금/예금" 또는 "부동산" 자산에만 사용할 수 있습니다.');
      return;
    }

    const nextAmount = isCash ? 1 : target.amount > 0 ? target.amount : 1;
    const nextCurrentPrice = isCash ? newBalance : newBalance / nextAmount;

    const applyLocal = () => {
      setAssets((prev) =>
        prev.map((asset) =>
          asset.id === id
            ? {
              ...asset,
              amount: nextAmount,
              currentPrice: nextCurrentPrice,
              purchasePrice: isCash ? newBalance : asset.purchasePrice,
              realizedProfit: isCash ? 0 : asset.realizedProfit,
              cmaConfig: isCash ? (cmaConfig || undefined) : undefined,
            }
            : asset,
        ),
      );
    };

    if (target.backendId && isRemoteEnabled) {
      try {
        const payload: Record<string, unknown> = {
          current_price: nextCurrentPrice,
        };

        if (isCash) {
          payload.amount = 1;
          payload.purchase_price = newBalance;
          payload.realized_profit = 0;
          payload.cma_config = cmaConfig
            ? {
              principal: cmaConfig.principal,
              annual_rate: cmaConfig.annualRate,
              tax_rate: cmaConfig.taxRate,
              start_date: cmaConfig.startDate,
            }
            : null;
        } else {
          if (target.amount <= 0) {
            payload.amount = 1;
          }
          payload.cma_config = null;
        }

        await apiClient.updateAsset(target.backendId, payload);
        await loadPortfolioFromServer();
        return;
      } catch (error) {
        alertError('Update cash balance error', error, {
          default: '서버와 통신 중 오류가 발생했습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
          unauthorized: '잔액을 저장하지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '서버와 통신할 수 없습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
        });
      }
    }

    applyLocal();
  };

  const updateAsset = async (
    id: string,
    updates: {
      name?: string;
      ticker?: string;
      indexGroup?: string;
      category?: AssetCategory;
      amount?: number;
      purchasePrice?: number;
    },
  ): Promise<void> => {
    const target = assets.find((a) => a.id === id);
    if (!target) return;

    const applyLocal = () => {
      setAssets((prev) =>
        prev.map((asset) => {
          if (asset.id !== id) return asset;
          return {
            ...asset,
            name: updates.name !== undefined ? updates.name : asset.name,
            ticker: updates.ticker !== undefined ? updates.ticker : asset.ticker,
            indexGroup: updates.indexGroup !== undefined ? updates.indexGroup : asset.indexGroup,
            category: updates.category !== undefined ? updates.category : asset.category,
            amount: updates.amount !== undefined ? updates.amount : asset.amount,
            purchasePrice:
              updates.purchasePrice !== undefined ? updates.purchasePrice : asset.purchasePrice,
          };
        }),
      );
    };

    if (target.backendId && isRemoteEnabled) {
      try {
        const payload: any = {};
        if (updates.name !== undefined) payload.name = updates.name;
        if (updates.ticker !== undefined) payload.ticker = updates.ticker || null;
        if (updates.indexGroup !== undefined) payload.index_group = updates.indexGroup || null;
        if (updates.category !== undefined) payload.category = updates.category;
        if (updates.amount !== undefined) payload.amount = updates.amount;
        if (updates.purchasePrice !== undefined) payload.purchase_price = updates.purchasePrice;

        const backendAsset = await apiClient.updateAsset(target.backendId, payload);
        const mapped = mapBackendAssetToFrontend(backendAsset);
        setAssets((prev) =>
          prev.map((asset) => (asset.id === id ? mapped : asset)),
        );
        return;
      } catch (error) {
        alertError('Update asset error', error, {
          default: '서버와 통신 중 오류가 발생했습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
          unauthorized: '자산 정보를 저장하지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.',
          network: '서버와 통신할 수 없습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
        });
      }
    }

    applyLocal();
  };

  return {
    assets,
    tradeHistory,
    historyData,
    summaryFromServer,
    isSyncing,
    addAsset,
    deleteAsset,
    tradeAsset,
    syncPrices,
    updateAsset,
    updateCashBalance,
    restoreFromBackup,
  };
};
