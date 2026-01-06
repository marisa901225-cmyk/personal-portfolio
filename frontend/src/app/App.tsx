import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './Layout';

// 실제 페이지 컴포넌트들
import {
    DashboardPage,
    AssetsPage,
    TradesPage,
    ExchangePage,
    ExpensesPage,
    AiReportPage,
    AddAssetPage,
    SettingsPage,
} from '@/pages';

/**
 * App 컴포넌트는 라우팅만 담당합니다.
 * 모든 비즈니스 로직과 데이터 패칭은 각 페이지 컴포넌트에서 처리합니다.
 */
const App: React.FC = () => {
    return (
        <Routes>
            <Route path="/" element={<Layout />}>
                <Route index element={<Navigate to="/dashboard" replace />} />
                <Route path="dashboard" element={<DashboardPage />} />
                <Route path="assets" element={<AssetsPage />} />
                <Route path="trades" element={<TradesPage />} />
                <Route path="exchange" element={<ExchangePage />} />
                <Route path="expenses" element={<ExpensesPage />} />
                <Route path="ai-report" element={<AiReportPage />} />
                <Route path="add-asset" element={<AddAssetPage />} />
                <Route path="settings" element={<SettingsPage />} />
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
        </Routes>
    );
};

export default App;
