/**
 * 백엔드 API 통신 시 발생하는 에러 클래스
 */

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
