import { useQuery } from '@tanstack/react-query';
import { ApiClient, mapBackendAssetToFrontend, mapBackendTradesToFrontend } from '../lib/api';
import { Asset, AppSettings, TradeRecord } from '../lib/types';
import { queryKeys } from '../src/shared/api/queryKeys';

export const usePortfolioQueries = (settings: AppSettings, apiClient: ApiClient) => {
    const isRemoteEnabled = Boolean(settings.serverUrl && settings.apiToken);

    const assetsQuery = useQuery({
        queryKey: queryKeys.portfolio,
        queryFn: async () => {
            const data = await apiClient.fetchPortfolio();
            const mappedAssets = data.assets.map(mapBackendAssetToFrontend);
            const mappedTrades = mapBackendTradesToFrontend(data.trades, mappedAssets);
            return {
                assets: mappedAssets,
                tradeHistory: mappedTrades,
                summary: data.summary,
            };
        },
        enabled: isRemoteEnabled,
    });

    const snapshotsQuery = useQuery({
        queryKey: queryKeys.snapshots(365),
        queryFn: async () => {
            const data = await apiClient.fetchSnapshots(365);
            return data.map((snap) => {
                const d = new Date(snap.snapshot_at);
                return {
                    date: d.toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' }),
                    value: snap.total_value,
                };
            });
        },
        enabled: isRemoteEnabled,
    });

    const cashflowsQuery = useQuery({
        queryKey: queryKeys.cashflows,
        queryFn: async () => {
            const data = await apiClient.fetchCashflows();
            return data.map((cf) => ({
                year: cf.year.toString(),
                deposit: cf.deposit,
                withdrawal: cf.withdrawal,
                net: cf.net,
                note: cf.note ?? undefined,
            }));
        },
        enabled: isRemoteEnabled,
    });

    return {
        assetsQuery,
        snapshotsQuery,
        cashflowsQuery,
    };
};
