import type { RequestFn } from './core';
import type { BackendAiChatMessageResponse } from './types';

export const createAiChatMessage = (
    request: RequestFn,
    payload: {
        memo: string;
        instruction: string;
        max_tokens?: number;
        temperature?: number;
        mode?: 'memo' | 'ask' | 'rewrite';
    },
): Promise<BackendAiChatMessageResponse> =>
    request<BackendAiChatMessageResponse>('/api/ai-chat/messages', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
