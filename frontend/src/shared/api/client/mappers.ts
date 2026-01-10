/**
 * 백엔드 → 프론트엔드 타입 변환 함수
 */

import type { Asset, TradeRecord, FxTransactionRecord } from '@lib/types';
import type { BackendAsset, BackendTrade, BackendFxTransaction } from './types';

const safeNum = (val: any) => {
    const n = Number(val);
    return Number.isFinite(n) ? n : 0;
};

export const mapBackendAssetToFrontend = (backend: BackendAsset): Asset => ({
    id: backend.id.toString(),
    backendId: backend.id,
    name: backend.name,
    ticker: backend.ticker ?? undefined,
    category: backend.category as Asset['category'],
    amount: safeNum(backend.amount),
    currentPrice: safeNum(backend.current_price),
    currency: backend.currency,
    purchasePrice: backend.purchase_price != null ? safeNum(backend.purchase_price) : undefined,
    realizedProfit: safeNum(backend.realized_profit),
    indexGroup: backend.index_group ?? undefined,
    cmaConfig: backend.cma_config
        ? {
            principal: safeNum(backend.cma_config.principal),
            annualRate: safeNum(backend.cma_config.annual_rate),
            taxRate: safeNum(backend.cma_config.tax_rate),
            startDate: backend.cma_config.start_date,
        }
        : undefined,
});

export const mapBackendTradesToFrontend = (
    backendTrades: BackendTrade[],
    frontendAssets: Asset[],
): TradeRecord[] => {
    const assetMap = new Map<string, Asset>();
    frontendAssets.forEach((a) => assetMap.set(a.id, a));

    return backendTrades.map((t) => {
        const assetId = t.asset_id.toString();
        const asset = assetMap.get(assetId);
        return {
            id: t.id.toString(),
            assetId,
            assetName: t.asset_name ?? asset?.name ?? '알 수 없는 자산',
            ticker: t.asset_ticker ?? asset?.ticker,
            type: t.type,
            quantity: t.quantity,
            price: t.price,
            timestamp: t.timestamp,
            realizedDelta: t.realized_delta ?? undefined,
        };
    });
};

export const mapBackendFxToFrontend = (
    backend: BackendFxTransaction,
): FxTransactionRecord => ({
    id: backend.id.toString(),
    tradeDate: backend.trade_date,
    type: backend.type,
    currency: backend.currency,
    fxAmount: backend.fx_amount ?? undefined,
    krwAmount: backend.krw_amount ?? undefined,
    rate: backend.rate ?? undefined,
    description: backend.description ?? undefined,
    note: backend.note ?? undefined,
});
