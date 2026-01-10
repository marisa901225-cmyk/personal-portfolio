import type { BackendYearlyCashflow } from './types';
import type { RequestFn } from './core';

export const fetchCashflows = (request: RequestFn): Promise<BackendYearlyCashflow[]> =>
    request<BackendYearlyCashflow[]>('/api/cashflows/', { method: 'GET' });

export const createCashflow = (
    request: RequestFn,
    payload: {
        year: number;
        deposit: number;
        withdrawal: number;
        note?: string | null;
    },
): Promise<BackendYearlyCashflow> =>
    request<BackendYearlyCashflow>('/api/cashflows/', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const updateCashflow = (
    request: RequestFn,
    cashflowId: number,
    payload: {
        year?: number;
        deposit?: number;
        withdrawal?: number;
        note?: string | null;
    },
): Promise<BackendYearlyCashflow> =>
    request<BackendYearlyCashflow>(`/api/cashflows/${cashflowId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
    });

export const deleteCashflow = (request: RequestFn, cashflowId: number): Promise<void> =>
    request<void>(`/api/cashflows/${cashflowId}`, { method: 'DELETE' });

export const uploadStatement = (
    request: RequestFn,
    file: File,
): Promise<{ message: string; added: number; skipped: number; total_parsed: number }> => {
    const formData = new FormData();
    formData.append('file', file);

    return request<{ message: string; added: number; skipped: number; total_parsed: number }>(
        '/api/cashflows/upload',
        {
            method: 'POST',
            body: formData,
            headers: {},
        },
    );
};
