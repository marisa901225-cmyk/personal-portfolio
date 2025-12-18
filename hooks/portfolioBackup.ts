import type { Dispatch, SetStateAction } from 'react';
import { Asset, TradeRecord } from '../types';
import { ApiClient, BackendPortfolioResponse } from '../backendClient';
import { alertError, isApiErrorStatus, isNetworkError } from '../errors';
import type { ImportedAssetSnapshot } from './portfolioTypes';
import { validateImportedAssetSnapshotList } from './portfolioBackupValidation';

interface RestorePortfolioFromBackupParams {
  snapshot: ImportedAssetSnapshot[];
  isRemoteEnabled: boolean;
  apiClient: ApiClient;
  setAssets: Dispatch<SetStateAction<Asset[]>>;
  setTradeHistory: Dispatch<SetStateAction<TradeRecord[]>>;
  loadPortfolioFromServer: () => Promise<void>;
}

export const restorePortfolioFromBackup = async ({
  snapshot,
  isRemoteEnabled,
  apiClient,
  setAssets,
  setTradeHistory,
  loadPortfolioFromServer,
}: RestorePortfolioFromBackupParams): Promise<void> => {
  const validation = validateImportedAssetSnapshotList(snapshot);
  if (validation.errors.length > 0) {
    alert(
      `엑셀 백업 데이터에 문제가 있어 복원을 중단했습니다.\n\n${validation.errors.slice(0, 10).join('\n')}`,
    );
    return;
  }
  snapshot = validation.valid;

  const totals = snapshot.reduce(
    (acc, item) => {
      acc[item.currency] += item.amount * item.currentPrice;
      return acc;
    },
    { KRW: 0, USD: 0 } as Record<'KRW' | 'USD', number>,
  );

  if (typeof window !== 'undefined') {
    const warningBlock =
      validation.warnings.length > 0
        ? `\n\n[경고]\n${validation.warnings.slice(0, 8).join('\n')}`
        : '';
    const confirmed = window.confirm(
      `기존 포트폴리오를 모두 삭제하고,\n엑셀 백업 파일 내용(${snapshot.length}개 자산)으로 덮어쓸까요?\n\n합계(단순 합산): KRW ${Math.round(
        totals.KRW,
      ).toLocaleString('ko-KR')} / USD ${Math.round(totals.USD).toLocaleString('en-US')}\n\n이 작업은 되돌릴 수 없습니다.${warningBlock}`,
    );
    if (!confirmed) {
      return;
    }
  }

  // 서버 미연결 상태에서는 브라우저 메모리 내에서만 복원
  if (!isRemoteEnabled) {
    const restoredAssets: Asset[] = snapshot.map((item, index) => ({
      id: `local-${Date.now()}-${index}`,
      name: item.name,
      ticker: item.ticker,
      category: item.category,
      amount: item.amount,
      currentPrice: item.currentPrice,
      currency: item.currency,
      purchasePrice: item.purchasePrice,
      realizedProfit: item.realizedProfit,
    }));
    setAssets(restoredAssets);
    setTradeHistory([]);
    alert('엑셀 백업에서 포트폴리오를 복원했습니다.\n(현재 세션에서만 유지됩니다 — 서버 미연결)');
    return;
  }

  try {
    // 1) 현재 서버 포트폴리오 조회
    const current: BackendPortfolioResponse = await apiClient.fetchPortfolio();

    // 2) 기존 자산 모두 삭제
    let deleteFailures = 0;
    for (const asset of current.assets) {
      try {
        await apiClient.deleteAsset(asset.id);
      } catch (error) {
        deleteFailures += 1;
        if (isApiErrorStatus(error, 401) || isNetworkError(error)) {
          alertError('Delete asset during restore error', error, {
            default: '기존 자산 삭제 중 오류가 발생했습니다.\n서버 상태를 확인해주세요.',
            unauthorized: 'API 비밀번호가 올바르지 않습니다.',
            network: '서버와 통신할 수 없습니다.\n서버 연결을 확인해주세요.',
          });
          return;
        }
        console.error('Failed to delete asset during restore', error);
      }
    }

    if (deleteFailures > 0) {
      alert(
        `기존 자산 삭제 중 오류가 발생했습니다. (${deleteFailures}건)\n안전하게 복원을 중단했습니다.\n서버 상태를 확인한 뒤 다시 시도해주세요.`,
      );
      return;
    }

    // 3) 백업에서 가져온 자산들 생성
    let createFailures = 0;
    for (const item of snapshot) {
      const payload = {
        name: item.name,
        ticker: item.ticker,
        category: item.category,
        currency: item.currency,
        amount: item.amount,
        current_price: item.currentPrice,
        purchase_price: item.purchasePrice,
        realized_profit: item.realizedProfit ?? 0,
        index_group: null,
        cma_config: null,
      };

      try {
        await apiClient.createAsset(payload);
      } catch (error) {
        createFailures += 1;
        if (isApiErrorStatus(error, 401) || isNetworkError(error)) {
          alertError('Create asset during restore error', error, {
            default: '자산 생성 중 오류가 발생했습니다.\n서버 상태를 확인해주세요.',
            unauthorized: 'API 비밀번호가 올바르지 않습니다.',
            network: '서버와 통신할 수 없습니다.\n서버 연결을 확인해주세요.',
          });
          return;
        }
        console.error('Failed to create asset during restore', error);
      }
    }

    // 4) 최종 상태 다시 로드
    await loadPortfolioFromServer();
    if (createFailures > 0) {
      alert(
        `엑셀 백업에서 포트폴리오를 부분 복원했습니다.\n생성 실패: ${createFailures}건\n서버 자산 목록을 확인해주세요.`,
      );
    } else {
      alert('엑셀 백업에서 포트폴리오를 복원했습니다.');
    }
  } catch (error) {
    alertError('Restore from backup error', error, {
      default: '포트폴리오 복원 중 오류가 발생했습니다.\n서버 상태를 확인해주세요.',
      unauthorized: 'API 비밀번호가 올바르지 않습니다.',
      network: '서버와 통신할 수 없습니다.\n서버 연결을 확인해주세요.',
    });
  }
};
