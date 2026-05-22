import type { RequestFn } from './core';
import type { BackendAiMemo } from './types';

export const fetchAiMemos = (request: RequestFn): Promise<BackendAiMemo[]> =>
    request<BackendAiMemo[]>('/api/ai-memos/', { method: 'GET' });

export const createAiMemo = (
    request: RequestFn,
    payload: {
        title?: string;
        content?: string;
    } = {},
): Promise<BackendAiMemo> =>
    request<BackendAiMemo>('/api/ai-memos/', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const updateAiMemo = (
    request: RequestFn,
    memoId: number,
    payload: {
        title?: string;
        content?: string;
    },
): Promise<BackendAiMemo> =>
    request<BackendAiMemo>(`/api/ai-memos/${memoId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
    });

export const deleteAiMemo = (request: RequestFn, memoId: number): Promise<void> =>
    request<void>(`/api/ai-memos/${memoId}`, { method: 'DELETE' });
