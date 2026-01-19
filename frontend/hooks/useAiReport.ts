
import { useState, useCallback, useMemo, useEffect } from 'react';
import { ApiClient, BackendAiReportTextResponse, BackendSavedAiReport, BackendReportResponse, AiReportMeta } from '@/shared/api/client';
import { getUserErrorMessage } from '@/shared/errors';

interface UseAiReportProps {
    serverUrl: string;
    apiToken?: string;
}

export type GeneralPeriod = {
    year: number;
    month?: number | null;
    quarter?: number | null;
    half?: number | null;
};

export const useAiReport = ({ serverUrl, apiToken }: UseAiReportProps) => {
    const [query, setQuery] = useState('2025년 6월 리포트');
    const [maxTokens, setMaxTokens] = useState(8000);
    const [currentResult, setCurrentResult] = useState<BackendAiReportTextResponse | null>(null);
    const [streamedReport, setStreamedReport] = useState('');
    const [streamMeta, setStreamMeta] = useState<Omit<BackendAiReportTextResponse, 'report'> | null>(null);
    const [generalReport, setGeneralReport] = useState<BackendReportResponse | null>(null);
    const [generalPeriod, setGeneralPeriod] = useState<GeneralPeriod | null>(null);
    const [generalError, setGeneralError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [isGeneralLoading, setIsGeneralLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const [savedReports, setSavedReports] = useState<BackendSavedAiReport[]>([]);
    const [selectedReportId, setSelectedReportId] = useState<number | null>(null);
    const [isSavedLoading, setIsSavedLoading] = useState(false);
    const [deletingId, setDeletingId] = useState<number | null>(null);

    const isRemoteEnabled = Boolean(serverUrl && apiToken);
    const apiClient = useMemo(() => new ApiClient(serverUrl, apiToken), [serverUrl, apiToken]);

    const loadGeneralReport = useCallback(async (period: GeneralPeriod) => {
        if (!isRemoteEnabled) return;
        setIsGeneralLoading(true);
        setGeneralError(null);
        setGeneralPeriod(period);
        try {
            const data = await apiClient.fetchReport({
                year: period.year,
                month: period.month ?? undefined,
                quarter: period.quarter ?? undefined,
                half: period.half ?? undefined,
            });
            setGeneralReport(data);
        } catch (err) {
            setGeneralError(getUserErrorMessage(err, { default: '일반 리포트를 불러오지 못했습니다.' }));
        } finally {
            setIsGeneralLoading(false);
        }
    }, [apiClient, isRemoteEnabled]);

    const loadSavedReports = useCallback(async () => {
        if (!isRemoteEnabled) return;
        setIsSavedLoading(true);
        try {
            const data = await apiClient.fetchSavedReports();
            setSavedReports(data);
            if (data.length > 0 && selectedReportId === null) {
                setSelectedReportId(data[0].id);
            }
        } catch (err) {
            console.error('[useAiReport] Failed to load saved reports:', err);
        } finally {
            setIsSavedLoading(false);
        }
    }, [apiClient, isRemoteEnabled, selectedReportId]);

    useEffect(() => {
        if (isRemoteEnabled) void loadSavedReports();
    }, [isRemoteEnabled, loadSavedReports]);

    const handleGenerate = async () => {
        if (!isRemoteEnabled || isLoading) return;
        if (!query.trim()) {
            setError('리포트 요청 문장을 입력해주세요.');
            return;
        }

        setIsLoading(true);
        setError(null);
        setCurrentResult(null);
        setStreamedReport('');
        setStreamMeta(null);
        setGeneralReport(null);

        try {
            let fullText = '';
            let meta: AiReportMeta | null = null;

            await apiClient.fetchAiReportTextStream(
                { query, maxTokens },
                {
                    onMeta: (data) => {
                        meta = data;
                        setStreamMeta(data);
                        void loadGeneralReport({
                            year: data.period.year,
                            month: data.period.month ?? null,
                            quarter: data.period.quarter ?? null,
                            half: data.period.half ?? null,
                        });
                    },
                    onChunk: (chunk) => {
                        fullText += chunk;
                        setStreamedReport(fullText);
                    },
                }
            );

            if (!meta) throw new Error('AI 리포트 메타데이터를 받지 못했습니다.');

            const result: BackendAiReportTextResponse = { ...(meta as AiReportMeta), report: fullText };
            setCurrentResult(result);
            setStreamedReport('');
            setStreamMeta(null);

            const saved = await apiClient.saveReport({
                period_year: result.period.year,
                period_month: result.period.month,
                period_quarter: result.period.quarter,
                period_half: result.period.half,
                query,
                report: result.report,
                model: result.model,
                generated_at: result.generated_at,
            });
            setSavedReports((prev) => [saved, ...prev]);
            setSelectedReportId(saved.id);
        } catch (err) {
            setError(getUserErrorMessage(err, { default: 'AI 리포트 생성에 실패했습니다.' }));
        } finally {
            setIsLoading(false);
        }
    };

    const handleDelete = async (id: number) => {
        if (deletingId !== null) return;
        setDeletingId(id);
        try {
            await apiClient.deleteReport(id);
            setSavedReports((prev) => prev.filter((r) => r.id !== id));
            if (selectedReportId === id) setSelectedReportId(null);
        } catch (err) {
            console.error('[useAiReport] Failed to delete report:', err);
        } finally {
            setDeletingId(null);
        }
    };

    const handleSelectSaved = (id: number) => {
        const report = savedReports.find((item) => item.id === id);
        setSelectedReportId(id);
        setCurrentResult(null);
        setError(null);
        setGeneralError(null);
        if (report) {
            void loadGeneralReport({
                year: report.period_year,
                month: report.period_month ?? null,
                quarter: report.period_quarter ?? null,
                half: report.period_half ?? null,
            });
        }
    };

    return {
        state: {
            query,
            maxTokens,
            currentResult,
            streamedReport,
            streamMeta,
            generalReport,
            generalPeriod,
            generalError,
            isLoading,
            isGeneralLoading,
            error,
            savedReports,
            selectedReportId,
            isSavedLoading,
            deletingId,
            isRemoteEnabled,
        },
        handlers: {
            setQuery,
            setMaxTokens,
            handleGenerate,
            handleDelete,
            handleSelectSaved,
        },
    };
};
