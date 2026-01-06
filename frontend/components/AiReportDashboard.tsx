import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertCircle, Loader2, Sparkles, Trash2 } from 'lucide-react';
import {
  ApiClient,
  BackendAiReportTextResponse,
  BackendReportResponse,
  BackendSavedAiReport,
} from '../lib/api';
import { getUserErrorMessage } from '../lib/utils/errors';

interface AiReportDashboardProps {
  serverUrl: string;
  apiToken?: string;
}

type GeneralPeriod = {
  year: number;
  month?: number | null;
  quarter?: number | null;
  half?: number | null;
};

const MAX_TOKENS_LIMIT = 10000;
const MIN_TOKENS = 512;

const formatPeriodLabel = (report: {
  period_year?: number;
  period_month?: number | null;
  period_quarter?: number | null;
  period_half?: number | null;
  period?: GeneralPeriod;
}) => {
  const year = report.period_year ?? report.period?.year;
  const month = report.period_month ?? report.period?.month;
  const quarter = report.period_quarter ?? report.period?.quarter;
  const half = report.period_half ?? report.period?.half;

  if (month) {
    return `${year}-${String(month).padStart(2, '0')}`;
  }
  if (quarter) {
    return `${year} Q${quarter}`;
  }
  if (half) {
    return `${year} ${half === 1 ? '상반기' : '하반기'}`;
  }
  return `${year}년`;
};

export const AiReportDashboard: React.FC<AiReportDashboardProps> = ({ serverUrl, apiToken }) => {
  const [query, setQuery] = useState('2025년 6월 리포트');
  const [maxTokens, setMaxTokens] = useState(8000);
  const [currentResult, setCurrentResult] = useState<BackendAiReportTextResponse | null>(null);
  const [streamedReport, setStreamedReport] = useState('');
  const [streamMeta, setStreamMeta] = useState<Omit<BackendAiReportTextResponse, 'report'> | null>(null);
  const [generalReport, setGeneralReport] = useState<BackendReportResponse | null>(null);
  const [generalPeriod, setGeneralPeriod] = useState<GeneralPeriod | null>(null);
  const [generalNote, setGeneralNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGeneralLoading, setIsGeneralLoading] = useState(false);

  // 저장된 리포트 관련 상태
  const [savedReports, setSavedReports] = useState<BackendSavedAiReport[]>([]);
  const [selectedReportId, setSelectedReportId] = useState<number | null>(null);
  const [isSavedLoading, setIsSavedLoading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const isRemoteEnabled = Boolean(serverUrl && apiToken);
  const apiClient = useMemo(() => new ApiClient(serverUrl, apiToken), [serverUrl, apiToken]);

  // 저장된 리포트 목록 로드
  const loadSavedReports = useCallback(async () => {
    if (!isRemoteEnabled) return;
    setIsSavedLoading(true);
    try {
      const data = await apiClient.fetchSavedReports();
      setSavedReports(data);
      // 저장된 리포트가 있으면 가장 최신 선택
      if (data.length > 0 && selectedReportId === null) {
        setSelectedReportId(data[0].id);
      }
    } catch (err) {
      console.error('[AiReportDashboard] Failed to load saved reports:', err);
    } finally {
      setIsSavedLoading(false);
    }
  }, [apiClient, isRemoteEnabled, selectedReportId]);

  useEffect(() => {
    if (isRemoteEnabled) {
      void loadSavedReports();
    }
  }, [isRemoteEnabled, loadSavedReports]);

  // 선택된 리포트
  const selectedReport = useMemo(() => {
    if (currentResult) return null; // 새로 생성된 리포트가 있으면 우선
    return savedReports.find((r) => r.id === selectedReportId) ?? null;
  }, [savedReports, selectedReportId, currentResult]);

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
    setGeneralPeriod(null);
    setGeneralNote(null);
    setGeneralError(null);

    try {
      let fullText = '';
      let meta: BackendAiReportTextResponse | null = null;

      await apiClient.fetchAiReportTextStream(
        {
          query,
          maxTokens,
        },
        {
          onMeta: (data) => {
            meta = {
              generated_at: data.generated_at,
              period: data.period,
              model: data.model,
              report: '',
            };
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
        },
      );

      if (!meta) {
        throw new Error('AI 리포트 메타데이터를 받지 못했습니다.');
      }

      // Type assertion needed because TypeScript doesn't track callback mutations
      const metaData = meta as BackendAiReportTextResponse;
      const data: BackendAiReportTextResponse = {
        generated_at: metaData.generated_at,
        period: metaData.period,
        model: metaData.model,
        report: fullText,
      };
      setCurrentResult(data);
      setStreamedReport('');
      setStreamMeta(null);

      // 생성된 리포트 자동 저장
      try {
        const saved = await apiClient.saveReport({
          period_year: data.period.year,
          period_month: data.period.month,
          period_quarter: data.period.quarter,
          period_half: data.period.half,
          query,
          report: data.report,
          model: data.model,
          generated_at: data.generated_at,
        });
        setSavedReports((prev) => [saved, ...prev]);
        setSelectedReportId(saved.id);
      } catch (saveErr) {
        console.error('[AiReportDashboard] Failed to save report:', saveErr);
      }
    } catch (err) {
      setStreamedReport('');
      setStreamMeta(null);
      setError(
        getUserErrorMessage(err, {
          default: 'AI 리포트를 생성하지 못했습니다.',
          unauthorized: 'AI 리포트를 생성하지 못했습니다.\nAPI 비밀번호를 확인해주세요.',
          network: 'AI 리포트를 생성하지 못했습니다.\n서버 연결을 확인해주세요.',
        }),
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectSaved = (id: number) => {
    const report = savedReports.find((item) => item.id === id);
    setSelectedReportId(id);
    setCurrentResult(null); // 새로 생성한 결과 초기화
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

  const handleDelete = async (id: number) => {
    if (deletingId !== null) return;
    setDeletingId(id);
    try {
      await apiClient.deleteReport(id);
      setSavedReports((prev) => prev.filter((r) => r.id !== id));
      if (selectedReportId === id) {
        setSelectedReportId(null);
      }
    } catch (err) {
      console.error('[AiReportDashboard] Failed to delete report:', err);
    } finally {
      setDeletingId(null);
    }
  };

  const loadGeneralReport = useCallback(async (period: GeneralPeriod) => {
    if (!isRemoteEnabled) return;
    setIsGeneralLoading(true);
    setGeneralError(null);
    setGeneralPeriod(period);
    setGeneralNote(
      period.half != null && period.month == null && period.quarter == null
        ? '일반 리포트는 반기 미지원이라 연간 기준으로 표시합니다.'
        : null,
    );
    try {
      const data = await apiClient.fetchReport({
        year: period.year,
        month: period.month ?? undefined,
        quarter: period.quarter ?? undefined,
        half: period.half ?? undefined,
      });
      setGeneralReport(data);
    } catch (err) {
      setGeneralError(
        getUserErrorMessage(err, {
          default: '일반 리포트를 불러오지 못했습니다.',
          unauthorized: '일반 리포트를 불러오지 못했습니다.\nAPI 비밀번호를 확인해주세요.',
          network: '일반 리포트를 불러오지 못했습니다.\n서버 연결을 확인해주세요.',
        }),
      );
    } finally {
      setIsGeneralLoading(false);
    }
  }, [apiClient, isRemoteEnabled]);

  // 표시할 리포트 결정
  const displayReport = currentResult
    ? {
      report: currentResult.report,
      periodLabel: formatPeriodLabel({ period: currentResult.period }),
      generatedAt: currentResult.generated_at,
      model: currentResult.model,
      isNew: true,
    }
    : isLoading && (streamedReport || streamMeta)
      ? {
        report: streamedReport,
        periodLabel: streamMeta
          ? formatPeriodLabel({ period: streamMeta.period })
          : '생성 중',
        generatedAt: streamMeta?.generated_at,
        model: streamMeta?.model,
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

  const generalSummary = generalReport?.portfolio.summary ?? null;

  return (
    <section className="space-y-6">
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">AI 리포트 생성</h2>
            <p className="text-sm text-slate-500 mt-1">
              백엔드에서 AI가 리포트를 생성하고, 자동으로 저장됩니다.
            </p>
          </div>
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            <div className="flex-1 min-w-[220px]">
              <label className="text-xs text-slate-500" htmlFor="ai-report-query">
                요청 문장
              </label>
              <input
                id="ai-report-query"
                type="text"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="예: 2025년 6월 리포트, 2025년 2분기 리포트, 올해 연간 리포트"
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-slate-500" htmlFor="ai-report-tokens">
                토큰
              </label>
              <input
                id="ai-report-tokens"
                type="number"
                min={MIN_TOKENS}
                max={MAX_TOKENS_LIMIT}
                value={maxTokens}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (!Number.isFinite(value)) return;
                  const clamped = Math.min(Math.max(value, MIN_TOKENS), MAX_TOKENS_LIMIT);
                  setMaxTokens(clamped);
                }}
                className="w-24 px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-700"
              />
            </div>
            <button
              type="button"
              onClick={handleGenerate}
              disabled={!isRemoteEnabled || isLoading}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-colors ${!isRemoteEnabled || isLoading
                ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                : 'bg-indigo-600 text-white hover:bg-indigo-700'
                }`}
            >
              {isLoading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  생성 중...
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  리포트 생성
                </>
              )}
            </button>
          </div>
        </div>

        {!isRemoteEnabled && (
          <div className="mt-4 text-sm text-slate-500">
            서버 URL과 API 비밀번호를 먼저 설정해주세요.
          </div>
        )}

        <div className="mt-4 text-xs text-slate-500">
          연간 요청은 GPT-5.2 Pro, 월/분기/반기는 GPT-5.2를 사용합니다.
        </div>

        {error && (
          <div className="mt-4 bg-red-50 text-red-600 p-3 rounded-lg text-sm flex items-start gap-2">
            <AlertCircle size={18} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {!error && (
          <div className="mt-4 text-xs text-slate-500">
            요청 문장 예시: 2025년 6월 리포트 / 2025년 2분기 리포트 / 2025년 상반기 리포트 / 올해 연간 리포트
          </div>
        )}
      </div>

      {/* 저장된 리포트 목록 */}
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

      {/* 리포트 결과 */}
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
            {generalNote && (
              <div className="mb-3 text-xs text-amber-600 bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
                {generalNote}
              </div>
            )}
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
    </section>
  );
};
