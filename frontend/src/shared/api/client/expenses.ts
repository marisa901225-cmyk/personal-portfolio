import type {
    BackendExpense,
    BackendExpenseUploadResult,
} from './types';
import type { RequestFn } from './core';

export const fetchCategories = (request: RequestFn): Promise<string[]> =>
    request<string[]>('/api/expenses/categories');

export const triggerLearning = (request: RequestFn): Promise<{ added: number; updated: number }> =>
    request<{ added: number; updated: number }>('/api/expenses/learn', {
        method: 'POST',
    });

export const fetchExpenses = (
    request: RequestFn,
    params?: {
        year?: number;
        month?: number;
        category?: string;
        includeDeleted?: boolean;
    },
    options: { signal?: AbortSignal } = {},
): Promise<BackendExpense[]> => {
    const search = new URLSearchParams();
    if (params?.year != null) search.set('year', params.year.toString());
    if (params?.month != null) search.set('month', params.month.toString());
    if (params?.category) search.set('category', params.category);
    if (params?.includeDeleted) search.set('include_deleted', 'true');
    const qs = search.toString();
    return request<BackendExpense[]>(`/api/expenses${qs ? `?${qs}` : ''}`, {
        method: 'GET',
        signal: options.signal,
    });
};

export const deleteExpense = (
    request: RequestFn,
    expenseId: number,
): Promise<{ status: string; deleted_at?: string | null }> =>
    request<{ status: string; deleted_at?: string | null }>(`/api/expenses/${expenseId}`, {
        method: 'DELETE',
    });

export const restoreExpense = (
    request: RequestFn,
    expenseId: number,
): Promise<BackendExpense> =>
    request<BackendExpense>(`/api/expenses/${expenseId}/restore`, {
        method: 'POST',
    });

export const updateExpense = (
    request: RequestFn,
    expenseId: number,
    payload: Partial<BackendExpense>,
): Promise<BackendExpense> =>
    request<BackendExpense>(`/api/expenses/${expenseId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
    });

export const uploadExpenseFile = (
    request: RequestFn,
    file: File,
): Promise<BackendExpenseUploadResult> => {
    const formData = new FormData();
    formData.append('file', file);

    return request<BackendExpenseUploadResult>('/api/expenses/upload', {
        method: 'POST',
        body: formData,
        headers: {},
    });
};
