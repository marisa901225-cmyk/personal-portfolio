/**
 * API Client 훅
 * 
 * 기존 lib/api/ApiClient를 React Query와 함께 사용하기 위한 설정.
 * Settings에서 serverUrl과 apiToken을 가져와 ApiClient 인스턴스를 생성합니다.
 */

import { useMemo } from 'react';
import { ApiClient } from '@/shared/api/client';

export interface ApiConfig {
    serverUrl: string;
    apiToken?: string;
    cookieAuth?: boolean;
}

/**
 * ApiClient 인스턴스를 생성하는 훅
 * serverUrl이 변경될 때만 새 인스턴스를 생성합니다.
 */
export function useApiClient(config: ApiConfig): ApiClient | null {
    return useMemo(() => {
        if (!config.serverUrl) return null;
        return new ApiClient(config.serverUrl, config.apiToken);
    }, [config.serverUrl, config.apiToken]);
}

/**
 * API 설정이 유효한지 확인
 */
export function isApiEnabled(config: ApiConfig): boolean {
    return Boolean(config.serverUrl && (config.apiToken || config.cookieAuth));
}
