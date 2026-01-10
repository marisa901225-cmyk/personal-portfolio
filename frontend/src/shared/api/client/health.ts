import type { BackendHealthResponse } from './types';
import type { RequestFn } from './core';

export const checkHealth = (request: RequestFn): Promise<BackendHealthResponse> =>
    request<BackendHealthResponse>('/api/health', { method: 'GET' });
