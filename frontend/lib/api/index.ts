/**
 * lib/api - 백엔드 API 통신 모듈
 *
 * 기존 backendClient.ts를 분할하여 역할별로 정리:
 * - types.ts: 백엔드 응답 타입 정의
 * - errors.ts: NetworkError, ApiError
 * - mappers.ts: 백엔드→프론트 변환 함수
 * - client.ts: ApiClient 클래스
 */

export * from './types';
export * from './errors';
export * from './mappers';
export { ApiClient } from './client';
