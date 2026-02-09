/**
 * Exchange Page (환전 내역)
 */

import React from 'react';
import { ExchangeHistory } from '@components/ExchangeHistory';
import { useSettings } from '@hooks/useSettings';

export const ExchangePage: React.FC = () => {
    const { settings, setSettings } = useSettings();

    return (
        <ExchangeHistory
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
            cookieAuth={settings.cookieAuth}
            onFxBaseUpdated={(value) => setSettings((prev) => ({ ...prev, usdFxBase: value }))}
        />
    );
};

export default ExchangePage;
