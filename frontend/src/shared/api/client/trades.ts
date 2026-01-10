import type { TradeType } from '@lib/types';
import type { BackendTrade } from './types';
import type { RequestFn } from './core';

export const fetchTrades = (
    request: RequestFn,
    params?: {
        limit?: number;
        beforeId?: number;
        assetId?: number;
    },
): Promise<BackendTrade[]> => {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set('limit', params.limit.toString());
    if (params?.beforeId != null) search.set('before_id', params.beforeId.toString());
    if (params?.assetId != null) search.set('asset_id', params.assetId.toString());
    const qs = search.toString();
    return request<BackendTrade[]>(`/api/trades${qs ? `?${qs}` : ''}`, { method: 'GET' });
};

export const createTrade = (
    request: RequestFn,
    assetId: number,
    type: TradeType,
    quantity: number,
    price: number,
): Promise<BackendTrade> =>
    request<BackendTrade>(`/api/assets/${assetId}/trades`, {
        method: 'POST',
        body: JSON.stringify({
            asset_id: assetId,
            type,
            quantity,
            price,
        }),
    });
