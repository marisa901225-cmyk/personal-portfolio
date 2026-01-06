
import { useInfiniteQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { ApiClient, mapBackendTradesToFrontend } from '../lib/api';
import type { Asset, TradeRecord } from '../lib/types';

interface UseTradeHistoryProps {
    serverUrl: string;
    apiToken?: string;
    assets: Asset[];
    enabled?: boolean;
}

const PAGE_SIZE = 100;

export const useTradeHistory = ({
    serverUrl,
    apiToken,
    assets,
    enabled = true,
}: UseTradeHistoryProps) => {
    const apiClient = useMemo(() => {
        return new ApiClient(serverUrl, apiToken);
    }, [serverUrl, apiToken]);

    const query = useInfiniteQuery({
        queryKey: ['tradeHistory', serverUrl, apiToken],
        queryFn: async ({ pageParam }) => {
            const backendTrades = await apiClient.fetchTrades({
                limit: PAGE_SIZE,
                beforeId: pageParam ?? undefined,
            });
            return backendTrades;
        },
        initialPageParam: null as number | null,
        getNextPageParam: (lastPage) => {
            if (!lastPage || lastPage.length < PAGE_SIZE) return undefined;
            const lastTrade = lastPage[lastPage.length - 1];
            return lastTrade.id;
        },
        enabled: enabled && !!serverUrl && !!apiToken,
        select: (data) => {
            // Flatten valid pages
            const allBackendTrades = data.pages.flat();
            // Map to frontend structure
            return {
                pages: data.pages,
                pageParams: data.pageParams,
                trades: mapBackendTradesToFrontend(allBackendTrades, assets),
            };
        },
    });

    return {
        trades: query.data?.trades ?? [],
        isLoading: query.isLoading,
        isError: query.isError,
        error: query.error,
        fetchNextPage: query.fetchNextPage,
        hasNextPage: query.hasNextPage,
        isFetchingNextPage: query.isFetchingNextPage,
        refetch: query.refetch,
    };
};
