/**
 * 에러 모듈 통합
 * 
 * lib/api/errors.ts + lib/utils/errors.ts 통합
 */

// ==================== 에러 클래스 ====================

export class NetworkError extends Error {
    constructor(public readonly url: string, cause?: unknown) {
        super(`Network request failed: ${url}`, { cause });
        this.name = 'NetworkError';
    }
}

export class ApiError extends Error {
    constructor(
        public readonly status: number,
        public readonly statusText: string,
        public readonly url: string,
        public readonly bodyText?: string,
    ) {
        super(
            `API Request Failed: ${status} ${statusText}${bodyText ? ` - ${bodyText}` : ''}`,
        );
        this.name = 'ApiError';
    }
}

// ==================== 타입 ====================

export type UserErrorMessages = {
    default: string;
    unauthorized?: string;
    rateLimited?: string;
    network?: string;
    clientError?: string;  // 4xx errors (except 401, 429)
    serverError?: string;  // 5xx errors
};

// ==================== 상수 ====================

export const APP_ERROR_EVENT = 'app:error';

// ==================== 헬퍼 함수 ====================

export const isNetworkError = (error: unknown): boolean => {
    if (error instanceof NetworkError) return true;
    if (error instanceof TypeError) return true;
    return false;
};

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

export const isApiErrorStatus = (error: unknown, status: number): boolean =>
    error instanceof ApiError && error.status === status;

export const getUserErrorMessage = (error: unknown, messages: UserErrorMessages): string => {
    if (isApiError(error)) {
        if (isApiErrorStatus(error, 401) && messages.unauthorized) return messages.unauthorized;
        if (isApiErrorStatus(error, 429) && messages.rateLimited) return messages.rateLimited;

        if (error.status >= 400 && error.status < 500 && messages.clientError) {
            return messages.clientError;
        }

        if (error.status >= 500 && messages.serverError) {
            return messages.serverError;
        }

        return messages.default;
    }

    if (isNetworkError(error)) {
        return messages.network ?? messages.default;
    }

    return messages.default;
};

export const alertError = (context: string, error: unknown, messages: UserErrorMessages): void => {
    console.error(context, error);
    if (typeof window !== 'undefined') {
        const message = getUserErrorMessage(error, messages);
        if (typeof window.dispatchEvent === 'function') {
            window.dispatchEvent(new CustomEvent(APP_ERROR_EVENT, { detail: message }));
            return;
        }
        window.alert(message);
    }
};
