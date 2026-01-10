/**
 * Expense Mutations
 * 
 * 가계부 수정/삭제를 위한 Mutation 훅들
 */

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiClient, BackendExpense } from '@/shared/api/client';
import { queryKeys } from '../queryKeys';

/**
 * 지출 수정 Mutation
 */
export function useUpdateExpense(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async ({ expenseId, payload }: { expenseId: number; payload: Partial<BackendExpense> }) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.updateExpense(expenseId, payload);
        },
        onSuccess: () => {
            // 모든 expense 쿼리 무효화
            queryClient.invalidateQueries({ queryKey: ['expenses'] });
        },
    });
}

/**
 * 지출 삭제 Mutation
 */
export function useDeleteExpense(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (expenseId: number) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.deleteExpense(expenseId);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['expenses'] });
        },
    });
}

/**
 * 지출 복원 Mutation
 */
export function useRestoreExpense(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (expenseId: number) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.restoreExpense(expenseId);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['expenses'] });
        },
    });
}

/**
 * 지출 파일 업로드 Mutation
 */
export function useUploadExpenseFile(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async (file: File) => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.uploadExpenseFile(file);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['expenses'] });
        },
    });
}

/**
 * 카테고리 학습 트리거 Mutation
 */
export function useTriggerLearning(apiClient: ApiClient | null) {
    const queryClient = useQueryClient();

    return useMutation({
        mutationFn: async () => {
            if (!apiClient) throw new Error('API client not configured');
            return apiClient.triggerLearning();
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['expenses'] });
        },
    });
}
