
import React from 'react';
import { Loader2 } from 'lucide-react';

interface ReportViewProps {
    displayReport: any;
    isLoading: boolean;
    isGeneralLoading: boolean;
    generalReport: any;
    generalPeriod: any;
    generalError: string | null;
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

export const ReportView: React.FC<ReportViewProps> = ({
    displayReport,
    isLoading,
    isGeneralLoading,
    generalReport,
    generalPeriod,
    generalError,
}) => {
    const generalSummary = generalReport?.portfolio.summary ?? null;

    return (
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
            <div className="flex items-center justify-between gap-3">
                <div>
                    <h2 className="text-lg font-semibold text-slate-900">AI 리포트 결과</h2>
                    <p className="text-sm text-slate-500 mt-1">
                        {displayReport?.isNew ? '방금 생성된 리포트입니다.' : '선택된 리포트를 표시합니다.'}
                    </p>
                </div>
                {displayReport && (
                    <div className="text-xs text-slate-400 text-right">
                        <div>기간: {displayReport.periodLabel}</div>
                        {displayReport.generatedAt && (
                            <div>생성: {new Date(displayReport.generatedAt).toLocaleString('ko-KR')}</div>
                        )}
                        {displayReport.model && <div>모델: {displayReport.model}</div>}
                    </div>
                )}
            </div>

            <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
                {/* AI Report Section */}
                <div>
                    <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm font-semibold text-slate-800">AI 리포트</h3>
                        {isLoading && (
                            <div className="flex items-center gap-2 text-xs text-slate-500">
                                <Loader2 size={14} className="animate-spin" />
                                생성 중
                            </div>
                        )}
                    </div>
                    {!displayReport && !isLoading && (
                        <div className="text-sm text-slate-400 text-center py-8">
                            리포트를 선택하거나 새로 생성해주세요.
                        </div>
                    )}
                    {displayReport?.report && (
                        <div className="whitespace-pre-wrap text-sm text-slate-700 leading-relaxed">
                            {displayReport.report}
                        </div>
                    )}
                </div>

                {/* General Report (Comparison) Section */}
                <div className="border-t border-slate-100 pt-6 lg:border-t-0 lg:border-l lg:pl-6 lg:pt-0">
                    <div className="flex items-center justify-between mb-3">
                        <div>
                            <h3 className="text-sm font-semibold text-slate-800">일반 리포트</h3>
                            <p className="text-xs text-slate-500 mt-1">
                                요약 수치와 건수 기준으로 비교합니다.
                            </p>
                        </div>
                        {isGeneralLoading && (
                            <Loader2 size={14} className="animate-spin text-slate-400" />
                        )}
                    </div>

                    {generalError && (
                        <div className="mb-3 text-xs text-rose-600 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">
                            {generalError}
                        </div>
                    )}

                    {!generalReport && !generalError && !isGeneralLoading && (
                        <div className="text-sm text-slate-400 text-center py-8">
                            비교할 일반 리포트를 불러오지 않았습니다.
                        </div>
                    )}

                    {generalReport && generalSummary && (
                        <div className="space-y-4 text-sm text-slate-700">
                            {generalPeriod && (
                                <div className="text-xs text-slate-400">
                                    기간: {formatPeriodLabel({ period: generalPeriod })}
                                </div>
                            )}
                            <div className="grid grid-cols-2 gap-3 text-xs">
                                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                                    <div className="text-slate-400">총 평가액</div>
                                    <div className="text-sm font-semibold text-slate-800">
                                        {generalSummary.total_value.toLocaleString('ko-KR')}
                                    </div>
                                </div>
                                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                                    <div className="text-slate-400">총 매입액</div>
                                    <div className="text-sm font-semibold text-slate-800">
                                        {generalSummary.total_invested.toLocaleString('ko-KR')}
                                    </div>
                                </div>
                                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                                    <div className="text-slate-400">실현 손익</div>
                                    <div className="text-sm font-semibold text-slate-800">
                                        {generalSummary.realized_profit_total.toLocaleString('ko-KR')}
                                    </div>
                                </div>
                                <div className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                                    <div className="text-slate-400">평가 손익</div>
                                    <div className="text-sm font-semibold text-slate-800">
                                        {generalSummary.unrealized_profit_total.toLocaleString('ko-KR')}
                                    </div>
                                </div>
                            </div>
                            <div className="grid grid-cols-2 gap-3 text-xs">
                                <div className="rounded-lg border border-slate-100 bg-white p-3">
                                    <div className="text-slate-400">자산/거래</div>
                                    <div className="text-sm font-semibold text-slate-800">
                                        {generalReport.portfolio.assets.length} / {generalReport.portfolio.trades.length}
                                    </div>
                                </div>
                                <div className="rounded-lg border border-slate-100 bg-white p-3">
                                    <div className="text-slate-400">스냅샷/입출금</div>
                                    <div className="text-sm font-semibold text-slate-800">
                                        {generalReport.snapshots.length} / {generalReport.external_cashflows.length}
                                    </div>
                                </div>
                            </div>
                            <div className="text-xs text-slate-400">
                                생성: {new Date(generalReport.generated_at).toLocaleString('ko-KR')}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};
