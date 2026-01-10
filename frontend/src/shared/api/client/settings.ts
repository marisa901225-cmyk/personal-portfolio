import type { BackendSettings } from './types';
import type { RequestFn } from './core';

export const fetchSettings = (request: RequestFn): Promise<BackendSettings> =>
    request<BackendSettings>('/api/settings', { method: 'GET' });

export const updateSettings = (
    request: RequestFn,
    payload: BackendSettings,
): Promise<BackendSettings> =>
    request<BackendSettings>('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(payload),
    });
