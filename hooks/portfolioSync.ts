import type { Dispatch, SetStateAction } from 'react';
import { Asset, AppSettings, AssetCategory } from '../types';
import { ApiClient } from '../backendClient';
import { calculateCmaBalance } from '../cmaConfig';
import { alertError } from '../errors';

interface SyncPortfolioPricesParams {
  settings: AppSettings;
  assets: Asset[];
  apiClient: ApiClient;
  isRemoteEnabled: boolean;
  setAssets: Dispatch<SetStateAction<Asset[]>>;
  setIsSyncing: Dispatch<SetStateAction<boolean>>;
  loadPortfolioFromServer: () => Promise<void>;
}

export const syncPortfolioPrices = async ({
  settings,
  assets,
  apiClient,
  isRemoteEnabled,
  setAssets,
  setIsSyncing,
  loadPortfolioFromServer,
}: SyncPortfolioPricesParams): Promise<void> => {
  if (!settings.serverUrl) {
    alert('설정에서 홈서버 URL을 입력해주세요.');
    return;
  }

  const tickers = assets.filter((a) => a.ticker).map((a) => a.ticker as string);
  const hasCmaConfig = assets.some(
    (a) => a.category === AssetCategory.CASH && !!a.cmaConfig,
  );

  if (tickers.length === 0 && !hasCmaConfig) {
    alert('티커가 등록된 자산이 없습니다.');
    return;
  }

  setIsSyncing(true);
  try {
    let priceMap: Record<string, number> = {};

    if (tickers.length > 0) {
      priceMap = await apiClient.fetchPrices(tickers);
    }

    const now = new Date();
    if (isRemoteEnabled) {
      // CMA/발행어음 잔액 자동 계산 대상은 백엔드에도 함께 반영
      for (const asset of assets) {
        if (asset.backendId && asset.category === AssetCategory.CASH && asset.cmaConfig) {
          const newBalance = calculateCmaBalance(asset.cmaConfig, now);
          try {
            await apiClient.updateAsset(asset.backendId, {
              amount: 1,
              current_price: newBalance,
              purchase_price: newBalance,
              realized_profit: 0,
              cma_config: {
                principal: asset.cmaConfig.principal,
                annual_rate: asset.cmaConfig.annualRate,
                tax_rate: asset.cmaConfig.taxRate,
                start_date: asset.cmaConfig.startDate,
              },
            });
          } catch (error) {
            console.error('Failed to update CMA balance on server', error);
          }
        }
      }

      await loadPortfolioFromServer();
    } else {
      // 서버 미연결 상태에서는 기존처럼 로컬 상태만 갱신
      setAssets((prevAssets) =>
        prevAssets.map((asset) => {
          let updated = asset;

          if (asset.ticker && priceMap[asset.ticker]) {
            updated = { ...updated, currentPrice: priceMap[asset.ticker] };
          }

          if (asset.category === AssetCategory.CASH && asset.cmaConfig) {
            const newBalance = calculateCmaBalance(asset.cmaConfig, now);
            updated = {
              ...updated,
              amount: 1,
              currentPrice: newBalance,
              purchasePrice: newBalance,
              realizedProfit: 0,
            };
          }

          return updated;
        }),
      );
    }

    alert('최신 가격 정보를 업데이트했습니다.');
  } catch (error) {
    alertError('Sync Error', error, {
      default: `서버 연결 실패 (또는 오류 발생).\nURL: ${settings.serverUrl}`,
      unauthorized: 'API 비밀번호가 올바르지 않습니다.',
      rateLimited: '시세 제공자가 너무 많은 요청을 받아 잠시 차단했습니다.',
      network: `서버 연결 실패.\nURL: ${settings.serverUrl}`,
    });
  } finally {
    setIsSyncing(false);
  }
};
