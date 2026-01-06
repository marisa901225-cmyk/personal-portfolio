/**
 * 사용자 친화적 에러 메시지 유틸리티
 */

import { ApiError, NetworkError } from '../api/errors';

export type UserErrorMessages = {
    default: string;
    unauthorized?: string;
    rateLimited?: string;
    network?: string;
    clientError?: string;  // 4xx errors (except 401, 429)
    serverError?: string;  // 5xx errors
};

export const APP_ERROR_EVENT = 'app:error';

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
        // 특정 상태 코드 처리
        if (isApiErrorStatus(error, 401) && messages.unauthorized) return messages.unauthorized;
        if (isApiErrorStatus(error, 429) && messages.rateLimited) return messages.rateLimited;

        // 4xx 클라이언트 에러 (잘못된 요청, 리소스 없음 등)
        if (error.status >= 400 && error.status < 500 && messages.clientError) {
            return messages.clientError;
        }

        // 5xx 서버 에러
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
