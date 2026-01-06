/**
 * Expenses Query Hook
 * 
 * 가계부 데이터를 가져오는 React Query 훅
 */

import { useQuery, UseQueryOptions } from '@tanstack/react-query';
import { ApiClient, BackendExpense } from '@lib/api';
import { queryKeys } from '../queryKeys';

interface ExpensesQueryParams {
    year?: number;
    month?: number;
    category?: string;
    includeDeleted?: boolean;
}

/**
 * 지출/수입 내역 조회
 */
export function useExpensesQuery(
    apiClient: ApiClient | null,
    params?: ExpensesQueryParams,
    options?: Omit<UseQueryOptions<BackendExpense[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.expenses(params),
        queryFn: async ({ signal }) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchExpenses(params, { signal });
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 5, // 5분 (가계부는 자주 변경되지 않음)
        ...options,
    });
}

/**
 * 카테고리 목록 조회
 */
export function useExpenseCategoriesQuery(
    apiClient: ApiClient | null,
    options?: Omit<UseQueryOptions<string[], Error>, 'queryKey' | 'queryFn'>
) {
    return useQuery({
        queryKey: queryKeys.expenseCategories,
        queryFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.fetchCategories();
        },
        enabled: !!apiClient,
        staleTime: 1000 * 60 * 30, // 30분 (카테고리는 거의 변경되지 않음)
        ...options,
    });
}
