
import React from 'react';
import { Loader2, Trash2 } from 'lucide-react';
import { BackendSavedAiReport } from '@/shared/api/client';

interface SavedReportListProps {
    savedReports: BackendSavedAiReport[];
    selectedReportId: number | null;
    currentResult: any;
    handleSelectSaved: (id: number) => void;
    handleDelete: (id: number) => void;
    isSavedLoading: boolean;
    deletingId: number | null;
}

const formatPeriodLabel = (report: any) => {
    const year = report.period_year ?? report.period?.year;
    const month = report.period_month ?? report.period?.month;
    const quarter = report.period_quarter ?? report.period?.quarter;
    const half = report.period_half ?? report.period?.half;

    if (month) return `${year}-${String(month).padStart(2, '0')}`;
    if (quarter) return `${year} Q${quarter}`;
    if (half) return `${year} ${half === 1 ? '상반기' : '하반기'}`;
    return `${year}년`;
};

export const SavedReportList: React.FC<SavedReportListProps> = ({
    savedReports,
    selectedReportId,
    currentResult,
    handleSelectSaved,
    handleDelete,
    isSavedLoading,
    deletingId,
}) => {
    return (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h2 className="text-lg font-semibold text-slate-900">저장된 리포트</h2>
                    <p className="text-sm text-slate-500 mt-1">
                        이전에 생성한 리포트를 조회하고 관리합니다.
                    </p>
                </div>
                {isSavedLoading && <Loader2 size={16} className="animate-spin text-slate-400" />}
            </div>

            {savedReports.length === 0 && !isSavedLoading && (
                <div className="text-sm text-slate-400 text-center py-4">
                    저장된 리포트가 없습니다.
                </div>
            )}

            {savedReports.length > 0 && (
                <div className="space-y-2 max-h-[240px] overflow-y-auto">
                    {savedReports.map((report) => (
                        <div
                            key={report.id}
                            className={`flex items-center justify-between p-3 rounded-lg border transition-colors cursor-pointer ${selectedReportId === report.id && !currentResult
                                ? 'border-indigo-300 bg-indigo-50'
                                : 'border-slate-100 bg-slate-50 hover:bg-slate-100'
                                }`}
                            onClick={() => handleSelectSaved(report.id)}
                        >
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                    <span className="text-sm font-medium text-slate-800">
                                        {formatPeriodLabel(report)}
                                    </span>
                                    <span className="text-xs text-slate-400">
                                        {new Date(report.generated_at).toLocaleDateString('ko-KR')}
                                    </span>
                                    {report.model && (
                                        <span className="text-[10px] px-1.5 py-0.5 bg-slate-200 text-slate-500 rounded">
                                            {report.model}
                                        </span>
                                    )}
                                </div>
                                <div className="text-xs text-slate-500 truncate mt-0.5">
                                    {report.query}
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    handleDelete(report.id);
                                }}
                                disabled={deletingId === report.id}
                                className="ml-2 p-1.5 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-colors"
                                title="리포트 삭제"
                            >
                                {deletingId === report.id ? (
                                    <Loader2 size={14} className="animate-spin" />
                                ) : (
                                    <Trash2 size={14} />
                                )}
                            </button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};
