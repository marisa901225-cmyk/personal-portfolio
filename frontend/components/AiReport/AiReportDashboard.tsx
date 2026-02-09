
import React from 'react';
import { AlertCircle } from 'lucide-react';
import { useAiReport } from '../../hooks/useAiReport';
import { AiReportGenerator } from './AiReportGenerator';
import { SavedReportList } from './SavedReportList';
import { ReportView } from './ReportView';

interface AiReportDashboardProps {
    serverUrl: string;
    apiToken?: string;
    cookieAuth?: boolean;
}

const formatPeriodLabel = (report: {
    period_year?: number;
    period_month?: number | null;
    period_quarter?: number | null;
    period_half?: number | null;
    period?: { year: number; month?: number | null; quarter?: number | null; half?: number | null }
}) => {
    const year = report.period_year ?? report.period?.year;
    const month = report.period_month ?? report.period?.month;
    const quarter = report.period_quarter ?? report.period?.quarter;
    const half = report.period_half ?? report.period?.half;

    if (month) return `${year}-${String(month).padStart(2, '0')}`;
    if (quarter) return `${year} Q${quarter}`;
    if (half) return `${year} ${half === 1 ? '상반기' : '하반기'}`;
    return `${year}년`;
};

export const AiReportDashboard: React.FC<AiReportDashboardProps> = ({ serverUrl, apiToken, cookieAuth }) => {
    const { state, handlers } = useAiReport({ serverUrl, apiToken, cookieAuth });

    const selectedReport = state.currentResult
        ? null
        : state.savedReports.find((r) => r.id === state.selectedReportId) ?? null;

    const displayReport = state.currentResult
        ? {
            report: state.currentResult.report,
            periodLabel: formatPeriodLabel({ period: state.currentResult.period }),
            generatedAt: state.currentResult.generated_at,
            model: state.currentResult.model,
            isNew: true,
        }
        : state.isLoading && (state.streamedReport || state.streamMeta)
            ? {
                report: state.streamedReport,
                periodLabel: state.streamMeta
                    ? formatPeriodLabel({ period: state.streamMeta.period })
                    : '생성 중',
                generatedAt: state.streamMeta?.generated_at,
                model: state.streamMeta?.model,
                isNew: true,
            }
            : selectedReport
                ? {
                    report: selectedReport.report,
                    periodLabel: formatPeriodLabel(selectedReport),
                    generatedAt: selectedReport.generated_at,
                    model: selectedReport.model,
                    isNew: false,
                }
                : null;

    return (
        <section className="space-y-6">
            <AiReportGenerator
                query={state.query}
                setQuery={handlers.setQuery}
                maxTokens={state.maxTokens}
                setMaxTokens={handlers.setMaxTokens}
                handleGenerate={handlers.handleGenerate}
                isLoading={state.isLoading}
                isRemoteEnabled={state.isRemoteEnabled}
            />

            {state.error && (
                <div className="bg-red-50 text-red-600 p-3 rounded-xl text-sm flex items-start gap-2 mx-6">
                    <AlertCircle size={18} className="shrink-0 mt-0.5" />
                    <span>{state.error}</span>
                </div>
            )}

            <SavedReportList
                savedReports={state.savedReports}
                selectedReportId={state.selectedReportId}
                currentResult={Boolean(state.currentResult)}
                handleSelectSaved={handlers.handleSelectSaved}
                handleDelete={handlers.handleDelete}
                isSavedLoading={state.isSavedLoading}
                deletingId={state.deletingId}
            />

            <ReportView
                displayReport={displayReport}
                isLoading={state.isLoading}
                isGeneralLoading={state.isGeneralLoading}
                generalReport={state.generalReport}
                generalPeriod={state.generalPeriod ? {
                    ...state.generalPeriod,
                    start_date: '',
                    end_date: ''
                } : null}
                generalError={state.generalError}
            />
        </section>
    );
};
