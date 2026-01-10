import type {
    BackendPortfolioResponse,
    BackendRestoreAsset,
    BackendPortfolioRestoreResponse,
    BackendSnapshot,
} from './types';
import type { RequestFn } from './core';

export const fetchPortfolio = (request: RequestFn): Promise<BackendPortfolioResponse> =>
    request<BackendPortfolioResponse>('/api/portfolio', { method: 'GET' });

export const restorePortfolio = (
    request: RequestFn,
    assets: BackendRestoreAsset[],
): Promise<BackendPortfolioRestoreResponse> =>
    request<BackendPortfolioRestoreResponse>('/api/portfolio/restore', {
        method: 'POST',
        body: JSON.stringify({ assets }),
    });

export const fetchSnapshots = (request: RequestFn, days = 180): Promise<BackendSnapshot[]> =>
    request<BackendSnapshot[]>(`/api/portfolio/snapshots?days=${days}`, { method: 'GET' });

export const createSnapshot = (request: RequestFn): Promise<BackendSnapshot> =>
    request<BackendSnapshot>('/api/portfolio/snapshots', { method: 'POST' });
