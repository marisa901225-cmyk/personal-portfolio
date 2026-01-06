/**
 * Dashboard Page
 * 
 * React Query를 사용해 포트폴리오 데이터를 로드하고
 * 기존 Dashboard 컴포넌트를 렌더링합니다.
 */

import React from 'react';
import { Dashboard } from '@components/Dashboard';
import { useApiClient, isApiEnabled } from '@/shared/api/apiClient';
import { useAssetsQuery, useHistoryDataQuery, useCashflowsQuery, usePortfolioSummaryQuery } from '@/shared/api/queries';
import { useSettings } from '@hooks/useSettings';
import { Loader2 } from 'lucide-react';

export const DashboardPage: React.FC = () => {
    const { settings } = useSettings();
    const apiClient = useApiClient({
        serverUrl: settings.serverUrl,
        apiToken: settings.apiToken,
    });

    const enabled = isApiEnabled({ serverUrl: settings.serverUrl, apiToken: settings.apiToken });

    // Query 훅들
    const assetsQuery = useAssetsQuery(apiClient, { enabled });
    const summaryQuery = usePortfolioSummaryQuery(apiClient);
    const historyQuery = useHistoryDataQuery(apiClient, 365, { enabled });
    const cashflowsQuery = useCashflowsQuery(apiClient, { enabled });

    // 로딩 상태
    const isLoading = assetsQuery.isLoading || summaryQuery.isLoading;
    const isError = assetsQuery.isError || summaryQuery.isError;

    if (!enabled) {
        return (
            <div className="flex flex-col items-center justify-center py-20 text-center">
                <p className="text-slate-500">서버 연결이 필요합니다.</p>
                <p className="text-sm text-slate-400 mt-2">
                    설정에서 서버 URL과 API 토큰을 입력해주세요.
                </p>
            </div>
        );
    }

    if (isLoading) {
        return (
            <div className="flex flex-col items-center justify-center py-20">
                <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
                <p className="text-slate-500 mt-4">포트폴리오 로딩 중...</p>
            </div>
        );
    }

    if (isError) {
        return (
            <div className="flex flex-col items-center justify-center py-20 text-center">
                <p className="text-red-500">데이터를 불러오는데 실패했습니다.</p>
                <button
                    onClick={() => {
                        assetsQuery.refetch();
                        summaryQuery.refetch();
                    }}
                    className="mt-4 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700"
                >
                    다시 시도
                </button>
            </div>
        );
    }

    const assets = assetsQuery.data ?? [];
    const summary = summaryQuery.data;
    const historyData = historyQuery.data ?? [];
    const yearlyCashflows = cashflowsQuery.data ?? [];

    return (
        <Dashboard
            assets={assets}
            backendSummary={summary}
            usdFxBase={settings.usdFxBase}
            usdFxNow={settings.usdFxNow}
            targetIndexAllocations={settings.targetIndexAllocations}
            historyData={historyData}
            yearlyCashflows={yearlyCashflows}
            benchmarkName={settings.benchmarkName}
            benchmarkReturn={settings.benchmarkReturn}
            apiClient={apiClient!}
            onReload={() => {
                assetsQuery.refetch();
                cashflowsQuery.refetch();
                historyQuery.refetch();
            }}
        />
    );
};

export default DashboardPage;
