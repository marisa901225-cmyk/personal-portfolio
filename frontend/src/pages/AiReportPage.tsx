/**
 * AI Report Page
 */

import React from 'react';
import { AiReportDashboard } from '@components/AiReportDashboard';
import { useSettings } from '@hooks/useSettings';

export const AiReportPage: React.FC = () => {
    const { settings } = useSettings();

    return (
        <AiReportDashboard
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
            cookieAuth={settings.cookieAuth}
        />
    );
};

export default AiReportPage;
