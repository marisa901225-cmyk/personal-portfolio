/**
 * Trades Page (거래 내역)
 */

import React from 'react';
import { TradeHistoryAll } from '@components/TradeHistoryAll';
import { useApiClient, isApiEnabled } from '@/shared/api/apiClient';
import { useAssetsQuery } from '@/shared/api/queries';
import { useSettings } from '@hooks/useSettings';

export const TradesPage: React.FC = () => {
    const { settings } = useSettings();
    const apiClient = useApiClient({
        serverUrl: settings.serverUrl,
        apiToken: settings.apiToken,
    });

    const enabled = isApiEnabled({ serverUrl: settings.serverUrl, apiToken: settings.apiToken });
    const assetsQuery = useAssetsQuery(apiClient, { enabled });
    const assets = assetsQuery.data ?? [];

    return (
        <TradeHistoryAll
            variant="page"
            assets={assets}
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
        />
    );
};

export default TradesPage;
