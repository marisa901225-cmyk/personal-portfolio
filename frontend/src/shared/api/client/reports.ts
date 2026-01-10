import { ApiError, NetworkError } from './errors';
import type { CreateHeadersFn, RequestFn } from './core';
import type {
    BackendAiReportTextResponse,
    BackendReportResponse,
    BackendSavedAiReport,
} from './types';

export const fetchReport = (
    request: RequestFn,
    params: {
        year: number;
        month?: number;
        quarter?: number;
        half?: number;
    },
): Promise<BackendReportResponse> => {
    const search = new URLSearchParams();
    search.set('year', params.year.toString());

    if (params.month != null) {
        search.set('month', params.month.toString());
        return request<BackendReportResponse>(
            `/api/report/monthly?${search.toString()}`,
            { method: 'GET' },
        );
    }

    if (params.quarter != null) {
        search.set('quarter', params.quarter.toString());
        return request<BackendReportResponse>(
            `/api/report/quarterly?${search.toString()}`,
            { method: 'GET' },
        );
    }

    return request<BackendReportResponse>(
        `/api/report/yearly?${search.toString()}`,
        { method: 'GET' },
    );
};

export const fetchAiReportText = (
    request: RequestFn,
    params: {
        year?: number;
        month?: number;
        quarter?: number;
        query?: string;
        maxTokens?: number;
        model?: string;
    },
): Promise<BackendAiReportTextResponse> => {
    const search = new URLSearchParams();
    if (params.year != null) search.set('year', params.year.toString());
    if (params.month != null) search.set('month', params.month.toString());
    if (params.quarter != null) search.set('quarter', params.quarter.toString());
    if (params.query) search.set('query', params.query);
    if (params.maxTokens != null) search.set('max_tokens', params.maxTokens.toString());
    if (params.model) search.set('model', params.model);
    return request<BackendAiReportTextResponse>(
        `/api/report/ai/text?${search.toString()}`,
        { method: 'GET' },
    );
};

export const fetchAiReportTextStream = async (
    baseUrl: string,
    createHeaders: CreateHeadersFn,
    params: {
        year?: number;
        month?: number;
        quarter?: number;
        query?: string;
        maxTokens?: number;
        model?: string;
    },
    handlers: {
        onMeta: (meta: Omit<BackendAiReportTextResponse, 'report'>) => void;
        onChunk: (chunk: string) => void;
    },
): Promise<void> => {
    const search = new URLSearchParams();
    if (params.year != null) search.set('year', params.year.toString());
    if (params.month != null) search.set('month', params.month.toString());
    if (params.quarter != null) search.set('quarter', params.quarter.toString());
    if (params.query) search.set('query', params.query);
    if (params.maxTokens != null) search.set('max_tokens', params.maxTokens.toString());
    if (params.model) search.set('model', params.model);

    const url = `${baseUrl}/api/report/ai/text/stream?${search.toString()}`;
    let response: Response;
    try {
        response = await fetch(url, {
            method: 'GET',
            headers: {
                ...createHeaders(false),
                Accept: 'text/event-stream',
            },
        });
    } catch (error) {
        if (error instanceof Error && error.name === 'AbortError') {
            throw error;
        }
        throw new NetworkError(url, error);
    }

    if (!response.ok) {
        const errorText = await response.text();
        throw new ApiError(response.status, response.statusText, url, errorText);
    }

    if (!response.body) {
        throw new ApiError(500, 'Stream response body is empty', url);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const handleEvent = (rawEvent: string) => {
        const lines = rawEvent.split('\n');
        let event = 'message';
        const dataLines: string[] = [];
        for (const line of lines) {
            if (line.startsWith('event:')) {
                event = line.replace('event:', '').trim();
            } else if (line.startsWith('data:')) {
                dataLines.push(line.replace('data:', '').trimStart());
            }
        }
        const data = dataLines.join('\n');
        if (!data && event !== 'done') {
            return;
        }
        if (event === 'meta') {
            const parsed = JSON.parse(data) as Omit<BackendAiReportTextResponse, 'report'>;
            handlers.onMeta(parsed);
            return;
        }
        if (event === 'chunk') {
            handlers.onChunk(data);
            return;
        }
        if (event === 'error') {
            throw new Error(data || 'AI report stream failed');
        }
    };

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';
        for (const part of parts) {
            if (part.trim()) {
                handleEvent(part);
            }
        }
    }
};

export const fetchSavedReports = (request: RequestFn): Promise<BackendSavedAiReport[]> =>
    request<BackendSavedAiReport[]>('/api/report/saved', { method: 'GET' });

export const saveReport = (
    request: RequestFn,
    payload: {
        period_year: number;
        period_month?: number | null;
        period_quarter?: number | null;
        period_half?: number | null;
        query: string;
        report: string;
        model?: string | null;
        generated_at: string;
    },
): Promise<BackendSavedAiReport> =>
    request<BackendSavedAiReport>('/api/report/saved', {
        method: 'POST',
        body: JSON.stringify(payload),
    });

export const deleteReport = (request: RequestFn, reportId: number): Promise<void> =>
    request<void>(`/api/report/saved/${reportId}`, {
        method: 'DELETE',
    });
