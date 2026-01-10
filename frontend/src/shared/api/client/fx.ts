import type { FxTransactionType } from '@lib/types';
import type { BackendFxTransaction } from './types';
import type { RequestFn } from './core';

export const fetchFxTransactions = (
    request: RequestFn,
    params?: {
        limit?: number;
        beforeId?: number;
        kind?: FxTransactionType;
        startDate?: string;
        endDate?: string;
    },
): Promise<BackendFxTransaction[]> => {
    const search = new URLSearchParams();
    if (params?.limit != null) search.set('limit', params.limit.toString());
    if (params?.beforeId != null) search.set('before_id', params.beforeId.toString());
    if (params?.kind != null) search.set('kind', params.kind);
    if (params?.startDate) search.set('start_date', params.startDate);
    if (params?.endDate) search.set('end_date', params.endDate);
    const qs = search.toString();
    return request<BackendFxTransaction[]>(`/api/exchanges${qs ? `?${qs}` : ''}`, {
        method: 'GET',
    });
};

export const createFxTransaction = (
    request: RequestFn,
    payload: {
        trade_date: string;
        type: FxTransactionType;
        currency: 'KRW' | 'USD';
        fx_amount?: number | null;
        krw_amount?: number | null;
        rate?: number | null;
        description?: string | null;
        note?: string | null;
    },
): Promise<BackendFxTransaction> =>
    request<BackendFxTransaction>('/api/exchanges', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const updateFxTransaction = (
    request: RequestFn,
    recordId: number,
    payload: {
        trade_date?: string;
        type?: FxTransactionType;
        currency?: 'KRW' | 'USD';
        fx_amount?: number | null;
        krw_amount?: number | null;
        rate?: number | null;
        description?: string | null;
        note?: string | null;
    },
): Promise<BackendFxTransaction> =>
    request<BackendFxTransaction>(`/api/exchanges/${recordId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
    });

export const deleteFxTransaction = (request: RequestFn, recordId: number): Promise<void> =>
    request<void>(`/api/exchanges/${recordId}`, { method: 'DELETE' });
