/**
 * lib - 프로젝트 핵심 라이브러리
 *
 * 역할별로 분류된 모듈:
 * - api/: 백엔드 API 통신 (ApiClient, 타입, 에러)
 * - utils/: 유틸리티 함수 (포맷팅, CMA 계산, 에러 처리)
 * - types.ts: 프론트엔드 공통 타입
 */

export * from './types';
export * from './api';
export * from './utils';
