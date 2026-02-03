import type { RequestFn } from './core';
import {
    MemoryResponse,
    MemoryCreate,
    MemoryUpdate,
    MemorySearchRequest,
    MemoryCategory
} from './types';

/**
 * AI 장기 메모리 목록 조회
 */
export const fetchMemories = async (
    requestFn: RequestFn,
    params: {
        category?: MemoryCategory;
        min_importance?: number;
        include_expired?: boolean;
        limit?: number;
        offset?: number;
    } = {}
): Promise<MemoryResponse[]> => {
    const query = new URLSearchParams();
    if (params.category) query.append('category', params.category);
    if (params.min_importance) query.append('min_importance', params.min_importance.toString());
    if (params.include_expired) query.append('include_expired', 'true');
    if (params.limit) query.append('limit', params.limit.toString());
    if (params.offset) query.append('offset', params.offset.toString());

    const queryString = query.toString();
    const endpoint = `/api/memories/${queryString ? `?${queryString}` : ''}`;
    return requestFn(endpoint, { method: 'GET' });
};

/**
 * 특정 메모리 단건 조회
 */
export const getMemory = async (requestFn: RequestFn, id: number): Promise<MemoryResponse> => {
    return requestFn(`/api/memories/${id}`, { method: 'GET' });
};

/**
 * 새 메모리 생성
 */
export const createMemory = async (requestFn: RequestFn, payload: MemoryCreate): Promise<MemoryResponse> => {
    return requestFn('/api/memories/', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
};

/**
 * 기존 메모리 수정
 */
export const updateMemory = async (requestFn: RequestFn, id: number, payload: MemoryUpdate): Promise<MemoryResponse> => {
    return requestFn(`/api/memories/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
    });
};

/**
 * 메모리 삭제
 */
export const deleteMemory = async (requestFn: RequestFn, id: number): Promise<void> => {
    await requestFn(`/api/memories/${id}`, { method: 'DELETE' });
};

/**
 * 메모리 검색
 */
export const searchMemories = async (requestFn: RequestFn, params: MemorySearchRequest): Promise<MemoryResponse[]> => {
    return requestFn('/api/memories/search', {
        method: 'POST',
        body: JSON.stringify(params),
    });
};

/**
 * 만료된 메모리 일괄 정리
 */
export const cleanupExpiredMemories = async (requestFn: RequestFn): Promise<void> => {
    await requestFn('/api/memories/', { method: 'DELETE' });
};

/**
 * 장기기억 기반 AI 채팅 (스트리밍)
 */
export async function* chatWithMemories(
    params: {
        messages: { role: string; content: string }[];
        model?: string;
        session_id?: string;
    },
    baseUrl: string,
    createHeaders: (withJson?: boolean) => HeadersInit
): AsyncGenerator<string> {
    const url = `${baseUrl}/api/memories/chat`;
    const response = await fetch(url, {
        method: 'POST',
        headers: createHeaders(true),
        body: JSON.stringify(params),
    });

    if (!response.ok) {
        throw new Error(`Chat failed: ${response.statusText}`);
    }

    const reader = response.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        yield decoder.decode(value, { stream: true });
    }
}
