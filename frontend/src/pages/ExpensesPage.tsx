/**
 * Expenses Page
 * 
 * 가계부 페이지 - React Query를 사용해 데이터 로드
 */

import React from 'react';
import { ExpensesDashboard } from '@components/ExpensesDashboard';
import { useSettings } from '@hooks/useSettings';

export const ExpensesPage: React.FC = () => {
    const { settings } = useSettings();

    return (
        <ExpensesDashboard
            serverUrl={settings.serverUrl}
            apiToken={settings.apiToken}
            cookieAuth={settings.cookieAuth}
        />
    );
};

export default ExpensesPage;
