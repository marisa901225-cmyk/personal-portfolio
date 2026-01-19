import type {
    BackendAsset,
    BackendFxRateResponse,
    BackendTickerSearchResponse,
    AssetCreate,
    AssetUpdate,
} from './types';
import type { RequestFn } from './core';

export const createAsset = (request: RequestFn, payload: AssetCreate): Promise<BackendAsset> => {
    // Basic type guard
    if (!payload.name || !payload.category) {
        throw new Error('Invalid AssetCreate payload: name and category are required');
    }
    return request<BackendAsset>('/api/assets', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
};

export const deleteAsset = (request: RequestFn, assetId: number): Promise<void> =>
    request<void>(`/api/assets/${assetId}`, { method: 'DELETE' });

export const updateAsset = (
    request: RequestFn,
    asset_id: number,
    payload: AssetUpdate,
): Promise<BackendAsset> => {
    // Basic type guard
    if (typeof asset_id !== 'number') {
        throw new Error('Invalid updateAsset call: asset_id must be a number');
    }
    return request<BackendAsset>(`/api/assets/${asset_id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
    });
};

export const fetchPrices = (
    request: RequestFn,
    tickers: string[],
): Promise<Record<string, number>> =>
    request<Record<string, number>>('/api/kis/prices', {
        method: 'POST',
        body: JSON.stringify({ tickers }),
    });

export const fetchUsdKrwFxRate = (request: RequestFn): Promise<BackendFxRateResponse> =>
    request<BackendFxRateResponse>('/api/kis/fx/usdkrw', { method: 'GET' });

export const searchTicker = (
    request: RequestFn,
    query: string,
): Promise<BackendTickerSearchResponse> => {
    const q = query.trim();
    return request<BackendTickerSearchResponse>(
        `/api/search_ticker?q=${encodeURIComponent(q)}`,
        { method: 'GET' },
    );
};
