import { useEffect, useState } from 'react';
import { Asset, AppSettings, AssetCategory, TradeRecord, TradeType } from '../types';
import {
  STORAGE_KEYS,
  loadAssetsFromStorage,
  loadTradesFromStorage,
  showLocalStorageBackupWarning,
} from '../storage';
import {
  BackendPortfolioResponse,
  BackendSnapshot,
  BackendTrade,
  mapBackendAssetToFrontend,
  mapBackendTradesToFrontend,
} from '../backendClient';

interface HistoryPoint {
  date: string;
  value: number;
}

interface UsePortfolioResult {
  assets: Asset[];
  tradeHistory: TradeRecord[];
  historyData: HistoryPoint[];
  isSyncing: boolean;
  addAsset: (newAsset: Asset) => Promise<void>;
  deleteAsset: (id: string) => Promise<void>;
  tradeAsset: (id: string, type: TradeType, quantity: number, price: number) => Promise<void>;
  syncPrices: () => Promise<void>;
  updateTicker: (id: string, ticker?: string) => Promise<void>;
   updateCashBalance: (id: string, newBalance: number) => Promise<void>;
}

export const usePortfolio = (settings: AppSettings): UsePortfolioResult => {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [tradeHistory, setTradeHistory] = useState<TradeRecord[]>([]);
  const [historyData, setHistoryData] = useState<HistoryPoint[]>([]);
  const [isSyncing, setIsSyncing] = useState(false);

  const isRemoteEnabled = Boolean(settings.serverUrl && settings.apiToken);

  const loadFromLocal = () => {
    const localAssets = loadAssetsFromStorage();
    const localTrades = loadTradesFromStorage();
    setAssets(localAssets);
    setTradeHistory(localTrades);
    if (localAssets.length > 0) {
      showLocalStorageBackupWarning();
    }
  };

  const createHeaders = (withJson: boolean): HeadersInit => {
    const headers: HeadersInit = withJson ? { 'Content-Type': 'application/json' } : {};
    if (settings.apiToken) {
      headers['X-API-Token'] = settings.apiToken;
    }
    return headers;
  };

  const loadPortfolioFromServer = async (options?: {
    migrateFromLocalIfEmpty?: boolean;
  }): Promise<void> => {
    const { migrateFromLocalIfEmpty = false } = options ?? {};

    if (!isRemoteEnabled) {
      loadFromLocal();
      return;
    }

    const headers = createHeaders(false);

    try {
      const response = await fetch(`${settings.serverUrl}/api/portfolio`, {
        method: 'GET',
        headers,
      });

      if (!response.ok) {
        if (response.status === 401) {
          alert('포트폴리오를 불러오지 못했습니다.\nAPI 비밀번호가 올바른지 확인해주세요.');
        }
        loadFromLocal();
        return;
      }

      const data: BackendPortfolioResponse = await response.json();

      if (data.assets.length === 0 && migrateFromLocalIfEmpty) {
        const localAssets = loadAssetsFromStorage();
        const localTrades = loadTradesFromStorage();

        if (localAssets.length > 0) {
          const confirmUpload = window.confirm(
            '서버에 저장된 포트폴리오가 없습니다.\n이 브라우저의 기존 포트폴리오 데이터를 홈서버로 업로드할까요?',
          );
          if (confirmUpload) {
            try {
              for (const asset of localAssets) {
                const createPayload = {
                  name: asset.name,
                  ticker: asset.ticker,
                  category: asset.category,
                  currency: asset.currency,
                  amount: asset.amount,
                  current_price: asset.currentPrice,
                  purchase_price: asset.purchasePrice,
                  realized_profit: asset.realizedProfit ?? 0,
                  index_group: asset.indexGroup,
                };

                const createResp = await fetch(
                  `${settings.serverUrl}/api/assets`,
                  {
                    method: 'POST',
                    headers: createHeaders(true),
                    body: JSON.stringify(createPayload),
                  },
                );

                if (!createResp.ok) {
                  console.error('Asset upload failed', await createResp.text());
                }
              }

              const refreshed = await fetch(`${settings.serverUrl}/api/portfolio`, {
                method: 'GET',
                headers,
              });
              if (refreshed.ok) {
                const refreshedData: BackendPortfolioResponse = await refreshed.json();
                const mappedAssets = refreshedData.assets.map(mapBackendAssetToFrontend);
                const mappedTrades = mapBackendTradesToFrontend(
                  refreshedData.trades,
                  mappedAssets,
                );
                setAssets(mappedAssets);
                setTradeHistory(mappedTrades);
                alert('기존 localStorage 포트폴리오를 서버로 업로드했습니다.');
                return;
              }
            } catch (uploadError) {
              console.error('Migration upload error', uploadError);
            }
          }

          setAssets(localAssets);
          setTradeHistory(localTrades);
          if (localAssets.length > 0) {
            showLocalStorageBackupWarning();
          }
          return;
        }
      }

      const mappedAssets = data.assets.map(mapBackendAssetToFrontend);
      const mappedTrades = mapBackendTradesToFrontend(data.trades, mappedAssets);
      setAssets(mappedAssets);
      setTradeHistory(mappedTrades);
    } catch (error) {
      console.error('Failed to load portfolio from server', error);
      loadFromLocal();
    }
  };

  const loadHistoryFromServer = async (): Promise<void> => {
    if (!isRemoteEnabled) {
      setHistoryData([]);
      return;
    }

    const headers = createHeaders(false);

    try {
      const response = await fetch(
        `${settings.serverUrl}/api/portfolio/snapshots?days=180`,
        {
          method: 'GET',
          headers,
        },
      );

      if (!response.ok) {
        console.warn('Failed to load portfolio snapshots', response.status);
        return;
      }

      const data: BackendSnapshot[] = await response.json();
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
      console.error('Failed to load portfolio history from server', error);
    }
  };

  useEffect(() => {
    if (!isRemoteEnabled) {
      loadFromLocal();
      setHistoryData([]);
      return;
    }

    void loadPortfolioFromServer({ migrateFromLocalIfEmpty: true });
    void loadHistoryFromServer();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.serverUrl, settings.apiToken]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(STORAGE_KEYS.ASSETS, JSON.stringify(assets));
    } catch {
      // ignore
    }
  }, [assets]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(STORAGE_KEYS.TRADES, JSON.stringify(tradeHistory));
    } catch {
      // ignore
    }
  }, [tradeHistory]);

  const addAsset = async (newAsset: Asset): Promise<void> => {
    if (!isRemoteEnabled) {
      setAssets((prev) => [...prev, newAsset]);
      return;
    }

    const headers = createHeaders(true);

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
      };

      const resp = await fetch(`${settings.serverUrl}/api/assets`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        console.error('Failed to create asset on server', await resp.text());
        setAssets((prev) => [...prev, newAsset]);
        alert(
          '자산을 서버에 저장하지 못했습니다.\n이 세션에서는 브라우저(localStorage)에만 저장됩니다.',
        );
        return;
      }

      const backendAsset = await resp.json();
      const mapped = mapBackendAssetToFrontend(backendAsset);
      setAssets((prev) => [...prev, mapped]);
    } catch (error) {
      console.error('Create asset error', error);
      setAssets((prev) => [...prev, newAsset]);
      alert(
        '서버 연결에 실패했습니다.\n이 세션에서는 브라우저(localStorage)에만 저장됩니다.',
      );
    }
  };

  const deleteAsset = async (id: string): Promise<void> => {
    const target = assets.find((a) => a.id === id);

    if (target?.backendId && isRemoteEnabled) {
      const headers = createHeaders(false);
      try {
        const resp = await fetch(
          `${settings.serverUrl}/api/assets/${target.backendId}`,
          {
            method: 'DELETE',
            headers,
          },
        );
        if (!resp.ok) {
          console.error('Failed to delete asset on server', await resp.text());
        } else {
          await loadPortfolioFromServer();
        }
      } catch (error) {
        console.error('Delete asset error', error);
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
      const headers = createHeaders(true);

      try {
        const payload = {
          type,
          quantity,
          price,
        };

        const resp = await fetch(
          `${settings.serverUrl}/api/assets/${targetAsset.backendId}/trades`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify(payload),
          },
        );

        if (!resp.ok) {
          const text = await resp.text();
          console.error('Trade POST failed', text);
          alert('매수/매도 정보를 서버에 저장하지 못했습니다.');
        } else {
          const backendTrade: BackendTrade = await resp.json();

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
        }
      } catch (error) {
        console.error('Trade request error', error);
        alert('서버와 통신 중 오류가 발생했습니다. 현재 세션에서는 로컬로만 반영됩니다.');
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
    if (!settings.serverUrl) {
      alert('설정에서 홈서버 URL을 입력해주세요.');
      return;
    }

    const tickers = assets.filter((a) => a.ticker).map((a) => a.ticker as string);
    if (tickers.length === 0) {
      alert('티커가 등록된 자산이 없습니다.');
      return;
    }

    setIsSyncing(true);
    try {
      const headers = createHeaders(true);

      const response = await fetch(`${settings.serverUrl}/api/kis/prices`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ tickers }),
      });

      if (!response.ok) {
        if (response.status === 401) {
          alert(
            'API 비밀번호가 올바르지 않습니다.\n백엔드 서버의 API_TOKEN 값과 동일한 비밀번호를 입력했는지 확인해주세요.',
          );
          return;
        }

        if (response.status === 429) {
          alert(
            '시세 제공자가 너무 많은 요청을 받아 잠시 차단했습니다.\n잠시 후 다시 시도해주세요.',
          );
          return;
        }

        if (response.status >= 500 && response.status < 600) {
          alert(
            '홈서버 또는 시세 제공자에서 오류가 발생했습니다.\n잠시 후 다시 시도해주세요.',
          );
          return;
        }

        alert(`가격 동기화에 실패했습니다. (HTTP ${response.status})`);
        return;
      }

      const priceMap = await response.json();

      setAssets((prevAssets) =>
        prevAssets.map((asset) => {
          if (asset.ticker && priceMap[asset.ticker]) {
            return { ...asset, currentPrice: priceMap[asset.ticker] };
          }
          return asset;
        }),
      );

      alert('최신 가격 정보를 업데이트했습니다.');
    } catch (error) {
      console.error('Sync Error:', error);
      alert(
        `서버 연결 실패.\nURL: ${settings.serverUrl}\n홈서버가 켜져있고 Tailscale이 연결되었는지 확인하세요.`,
      );
    } finally {
      setIsSyncing(false);
    }
  };

  const updateCashBalance = async (id: string, newBalance: number): Promise<void> => {
    if (newBalance < 0) {
      alert('예비금은 0원보다 작을 수 없습니다.');
      return;
    }

    const target = assets.find((a) => a.id === id);
    if (!target) return;
    if (target.category !== AssetCategory.CASH) {
      alert('예비금 잔액 수정은 "현금/예금" 자산에만 사용할 수 있습니다.');
      return;
    }

    const applyLocal = () => {
      setAssets((prev) =>
        prev.map((asset) =>
          asset.id === id
            ? {
                ...asset,
                amount: 1,
                currentPrice: newBalance,
                purchasePrice: newBalance,
                realizedProfit: 0,
              }
            : asset,
        ),
      );
    };

    if (target.backendId && isRemoteEnabled) {
      const headers = createHeaders(true);

      try {
        const resp = await fetch(
          `${settings.serverUrl}/api/assets/${target.backendId}`,
          {
            method: 'PATCH',
            headers,
            body: JSON.stringify({
              amount: 1,
              current_price: newBalance,
              purchase_price: newBalance,
              realized_profit: 0,
            }),
          },
        );

        if (!resp.ok) {
          console.error('Failed to update cash balance on server', await resp.text());
          alert(
            '서버에 예비금 잔액을 저장하지 못했습니다.\n잠시 후 다시 시도해주세요.',
          );
        } else {
          const backendAsset = await resp.json();
          const mapped = mapBackendAssetToFrontend(backendAsset);
          setAssets((prev) =>
            prev.map((asset) => (asset.id === id ? mapped : asset)),
          );
          return;
        }
      } catch (error) {
        console.error('Update cash balance error', error);
        alert(
          '서버와 통신 중 오류가 발생했습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
        );
      }
    }

    applyLocal();
  };

  return {
    assets,
    tradeHistory,
    historyData,
    isSyncing,
    addAsset,
    deleteAsset,
    tradeAsset,
    syncPrices,
    updateTicker: async (id: string, ticker?: string): Promise<void> => {
      const trimmed = ticker?.trim() || undefined;
      const target = assets.find((a) => a.id === id);

      const applyLocal = () => {
        setAssets((prev) =>
          prev.map((asset) =>
            asset.id === id ? { ...asset, ticker: trimmed } : asset,
          ),
        );
      };

      if (!target) {
        applyLocal();
        return;
      }

      if (target.backendId && isRemoteEnabled) {
        const headers = createHeaders(true);

        try {
          const resp = await fetch(
            `${settings.serverUrl}/api/assets/${target.backendId}`,
            {
              method: 'PATCH',
              headers,
              body: JSON.stringify({ ticker: trimmed ?? null }),
            },
          );

          if (!resp.ok) {
            console.error('Failed to update ticker on server', await resp.text());
            alert(
              '서버에 티커를 저장하지 못했습니다.\n잠시 후 다시 시도해주세요.',
            );
          } else {
            const backendAsset = await resp.json();
            const mapped = mapBackendAssetToFrontend(backendAsset);
            setAssets((prev) =>
              prev.map((asset) => (asset.id === id ? mapped : asset)),
            );
            return;
          }
        } catch (error) {
          console.error('Update ticker error', error);
          alert(
            '서버와 통신 중 오류가 발생했습니다.\n현재 세션에서는 로컬로만 반영됩니다.',
          );
        }
      }

      applyLocal();
    },
    updateCashBalance,
  };
};
